from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .bdpan import BdpanError, BdpanRunner, PanDownloadReport, PanDownloadService
from .client import RobotsDeniedError, SiteClient
from .config import Settings, default_library_dir
from .database import LibraryDatabase
from .service import SyncService
from .storage import OneDriveLibrary


app = typer.Typer(no_args_is_help=True, help="Personal SaltTiger index and OneDrive library.")
console = Console()
LibraryOption = Annotated[
    Path,
    typer.Option("--library", envvar="SALTTIGER_LIBRARY_DIR", help="OneDrive library directory."),
]


def _components(library: Path, *, allow_disallowed: bool = False) -> tuple[Settings, LibraryDatabase, OneDriveLibrary, SiteClient]:
    settings = Settings(library_dir=library.expanduser().resolve())
    database = LibraryDatabase(settings.database_path)
    storage = OneDriveLibrary(settings.library_dir)
    client = SiteClient(
        user_agent=settings.user_agent,
        delay_seconds=settings.delay_seconds,
        timeout_seconds=settings.timeout_seconds,
        allow_disallowed=allow_disallowed,
    )
    return settings, database, storage, client


@app.command()
def sync(
    library: LibraryOption = default_library_dir(),
    limit: Annotated[int | None, typer.Option(min=1, help="Only process the newest N archive entries.")] = None,
    refresh: Annotated[bool, typer.Option(help="Re-fetch books already present in SQLite.")] = False,
    archive_html: Annotated[Path | None, typer.Option(exists=True, dir_okay=False, help="Offline archive HTML export.")] = None,
    detail_html_dir: Annotated[Path | None, typer.Option(exists=True, file_okay=False, help="Offline <slug>.html detail exports.")] = None,
    download_direct: Annotated[bool, typer.Option(help="Download only explicit PDF/EPUB/etc direct links.")] = False,
    download_pan: Annotated[bool, typer.Option(help="Download Baidu share links through the official bdpan CLI.")] = False,
    confirm_pan: Annotated[
        bool,
        typer.Option(help="Confirm that bdpan may transfer shares and write files locally."),
    ] = False,
    retry_pan_failed: Annotated[bool, typer.Option(help="Retry prior failed bdpan downloads.")] = False,
    bdpan_command: Annotated[
        str | None,
        typer.Option(envvar="SALTTIGER_BDPAN_COMMAND", help="bdpan command, for example 'wsl.exe bdpan'."),
    ] = None,
    allow_disallowed: Annotated[
        bool,
        typer.Option(help="Explicitly allow requests disallowed by the site's robots.txt."),
    ] = False,
) -> None:
    """Discover books, update SQLite and materialize them into OneDrive."""
    if download_pan and not confirm_pan:
        raise typer.BadParameter("--download-pan requires --confirm-pan because it transfers and downloads files")
    settings, database, storage, client = _components(library, allow_disallowed=allow_disallowed)
    try:
        with client:
            report = SyncService(database, storage, client).sync(
                limit=limit,
                refresh=refresh,
                archive_html=archive_html,
                detail_html_dir=detail_html_dir,
                download_direct=download_direct,
            )
        pan_report = None
        if download_pan:
            pan_report = _execute_pan_downloads(
                database,
                storage,
                limit=limit or 20,
                retry_failed=retry_pan_failed,
                bdpan_command=bdpan_command,
            )
    except RobotsDeniedError as error:
        console.print(f"[red]Stopped:[/red] {error}")
        raise typer.Exit(2) from error
    except BdpanError as error:
        console.print(f"[red]bdpan stopped:[/red] {error}")
        raise typer.Exit(2) from error
    console.print(
        f"Library: {settings.library_dir}\n"
        f"Discovered {report.discovered}, saved {report.saved}, "
        f"skipped {report.skipped}, failed {report.failed}."
    )
    for error in report.errors:
        console.print(f"[yellow]- {error}[/yellow]")
    if pan_report is not None:
        _print_pan_report(pan_report)
    if report.failed or (pan_report is not None and pan_report.failed):
        raise typer.Exit(1)


def _execute_pan_downloads(
    database: LibraryDatabase,
    storage: OneDriveLibrary,
    *,
    limit: int,
    retry_failed: bool,
    bdpan_command: str | None,
) -> PanDownloadReport:
    runner = BdpanRunner.discover(bdpan_command)
    status = runner.status()
    if not status.authenticated:
        raise BdpanError(
            "bdpan is installed but not authenticated. Use the official baidu-drive skill login.sh flow first."
        )
    return PanDownloadService(database, storage, runner).download_pending(
        limit=limit,
        retry_failed=retry_failed,
    )


def _print_pan_report(report: PanDownloadReport) -> None:
    console.print(
        f"Baidu Pan: planned {report.planned}, downloaded {report.downloaded}, failed {report.failed}."
    )
    for error in report.errors:
        console.print(f"[yellow]- {error}[/yellow]")


@app.command("bdpan-doctor")
def bdpan_doctor(
    bdpan_command: Annotated[
        str | None,
        typer.Option("--command", envvar="SALTTIGER_BDPAN_COMMAND", help="bdpan command override."),
    ] = None,
) -> None:
    """Check the official bdpan CLI and OAuth login status."""
    try:
        status = BdpanRunner.discover(bdpan_command).status()
    except BdpanError as error:
        console.print(f"[red]bdpan unavailable:[/red] {error}")
        raise typer.Exit(2) from error
    console.print(
        f"Command: {' '.join(status.command)}\n"
        f"Version: {status.version or '-'}\n"
        f"Authenticated: {'yes' if status.authenticated else 'no'}"
    )
    if not status.authenticated:
        console.print("Run the official baidu-drive skill login.sh flow; credentials are never stored here.")
        raise typer.Exit(2)


@app.command("download-pan")
def download_pan(
    library: LibraryOption = default_library_dir(),
    limit: Annotated[int, typer.Option(min=1, max=500)] = 20,
    retry_failed: Annotated[bool, typer.Option(help="Retry downloads currently marked failed.")] = False,
    confirm: Annotated[
        bool,
        typer.Option(help="Confirm share transfer and local file writes."),
    ] = False,
    bdpan_command: Annotated[
        str | None,
        typer.Option("--command", envvar="SALTTIGER_BDPAN_COMMAND", help="bdpan command override."),
    ] = None,
) -> None:
    """Download pending Baidu share links into their OneDrive book folders."""
    _, database, storage, client = _components(library)
    try:
        database.initialize()
        planned = database.pan_downloads(limit, retry_failed=retry_failed)
        if not confirm:
            console.print(f"Planned {len(planned)} Baidu share downloads. Re-run with --confirm to execute.")
            for task in planned:
                console.print(f"- #{task.book_id} {task.book_title}")
            return
        report = _execute_pan_downloads(
            database,
            storage,
            limit=limit,
            retry_failed=retry_failed,
            bdpan_command=bdpan_command,
        )
    except BdpanError as error:
        console.print(f"[red]bdpan stopped:[/red] {error}")
        raise typer.Exit(2) from error
    finally:
        client.close()
    _print_pan_report(report)
    if report.failed:
        raise typer.Exit(1)


@app.command("import-html")
def import_html(
    html: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    url: Annotated[str, typer.Option(help="Original SaltTiger detail URL.")],
    library: LibraryOption = default_library_dir(),
) -> None:
    """Import one detail page saved from a browser without crawling the site."""
    settings, database, storage, client = _components(library)
    try:
        book_id, book = SyncService(database, storage, client).import_detail_html(html, url)
    finally:
        client.close()
    console.print(f"Imported #{book_id}: {book.title}\n{settings.library_dir}")


@app.command("import-file")
def import_file(
    book_id: Annotated[int, typer.Argument(min=1)],
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    library: LibraryOption = default_library_dir(),
    replace: Annotated[bool, typer.Option(help="Replace a file with the same name.")] = False,
) -> None:
    """Copy an authorized/manual download into a book's OneDrive directory."""
    _, database, storage, client = _components(library)
    try:
        database.initialize()
        book = database.get(book_id)
        if book is None:
            console.print(f"[red]Unknown book id: {book_id}[/red]")
            raise typer.Exit(2)
        destination = storage.import_file(file, book, replace=replace)
        database.attach_local_file(book_id, destination)
    finally:
        client.close()
    console.print(f"Copied to {destination}")


def _show_books(books: list) -> None:
    table = Table(show_lines=False)
    table.add_column("ID", justify="right")
    table.add_column("Published")
    table.add_column("Title")
    table.add_column("Publisher")
    table.add_column("Tags")
    for book in books:
        table.add_row(
            str(book.id),
            book.published_at or "-",
            book.title,
            book.publisher or "-",
            ", ".join(book.tags),
        )
    console.print(table)


@app.command()
def search(
    query: str,
    library: LibraryOption = default_library_dir(),
    limit: Annotated[int, typer.Option(min=1, max=500)] = 50,
) -> None:
    """Search title, publisher and tags."""
    _, database, _, client = _components(library)
    try:
        database.initialize()
        _show_books(database.search(query, limit))
    finally:
        client.close()


@app.command()
def latest(
    library: LibraryOption = default_library_dir(),
    limit: Annotated[int, typer.Option(min=1, max=500)] = 20,
) -> None:
    """Show the newest indexed books."""
    _, database, _, client = _components(library)
    try:
        database.initialize()
        _show_books(database.latest(limit))
    finally:
        client.close()


@app.command()
def doctor(library: LibraryOption = default_library_dir()) -> None:
    """Show the resolved paths and initialize the local database."""
    settings, database, storage, client = _components(library)
    try:
        storage.ensure()
        database.initialize()
        console.print(f"Library:  {settings.library_dir}\nDatabase: {settings.database_path}\nBooks:    {database.count()}")
    finally:
        client.close()
