from __future__ import annotations

from functools import partial
from html import escape
from LSP.plugin import ClientNotification
from LSP.plugin import Error
from LSP.plugin import LspPlugin
from LSP.plugin import LspTextCommand
from LSP.plugin import LspWindowCommand
from LSP.plugin import Notification
from LSP.plugin import OnPreStartContext
from LSP.plugin import parse_uri
from LSP.plugin import PluginStartError
from LSP.plugin import Promise
from LSP.plugin import Request
from LSP.plugin import ServerResponse
from LSP.plugin import uri_from_view
from LSP.plugin import uri_handler
from LSP.plugin import WorkspaceFolder
from LSP.protocol import DocumentUri
from pathlib import Path
from typing import Any
from typing import ClassVar
from typing import List
from typing import TypedDict
from typing_extensions import NotRequired
from typing_extensions import override
import shutil
import sublime
import tarfile
import tempfile
import urllib.request
import zipfile

VERSION = '1.5.10'
DOWNLOAD_URL = 'https://github.com/tombi-toml/tombi/releases/download/v{version}/{archive}'
TARGETS = {
    'linux-arm64': 'aarch64-unknown-linux-musl',
    'linux-x64': 'x86_64-unknown-linux-musl',
    'osx-arm64': 'aarch64-apple-darwin',
    'osx-x64': 'x86_64-apple-darwin',
    'windows-arm64': 'aarch64-pc-windows-msvc',
    'windows-x64': 'x86_64-pc-windows-msvc',
}
IS_WINDOWS = sublime.platform() == 'windows'
BINARY_NAME = 'tombi.exe' if IS_WINDOWS else 'tombi'
# Saving one of these files makes the server reload its config (same list as the VS Code extension).
CONFIG_FILENAMES = ('.tombi.toml', 'tombi.toml', 'pyproject.toml', 'tombi/config.toml')


class SchemaInfo(TypedDict):
    uri: str
    title: NotRequired[str]
    description: NotRequired[str]
    tomlVersion: NotRequired[str]
    catalogUri: NotRequired[str]


class ListSchemasResponse(TypedDict):
    schemas: List[SchemaInfo]


class SchemaStatus(TypedDict):
    uri: str
    title: NotRequired[str]
    description: NotRequired[str]


class GetStatusResponse(TypedDict):
    tomlVersion: str
    source: str
    configPath: NotRequired[str]
    ignore: NotRequired[str]
    schema: NotRequired[SchemaStatus]


def plugin_loaded() -> None:
    LspTombiPlugin.register()


def plugin_unloaded() -> None:
    LspTombiPlugin.unregister()


class LspTombiPlugin(LspPlugin):

    # Source of the server binary for each window, from `on_pre_start_async` to the session status.
    _server_sources: ClassVar[dict[int, str]] = {}

    @classmethod
    @override
    def on_pre_start_async(cls, context: OnPreStartContext) -> None:
        if not any('$server_path' in arg for arg in context.configuration.command):
            source = 'custom'
        elif server_path := cls._find_workspace_binary(context.workspace_folders):
            source = 'venv'
            context.variables['server_path'] = str(server_path)
        else:
            source = 'bundled'
            context.variables['server_path'] = str(cls._install_managed_binary())
        if window := context.view.window():
            cls._server_sources[window.id()] = source

    @classmethod
    def _find_workspace_binary(cls, workspace_folders: list[WorkspaceFolder]) -> Path | None:
        bin_dir = 'Scripts' if IS_WINDOWS else 'bin'
        for folder in workspace_folders:
            if (binary_path := Path(folder.path, '.venv', bin_dir, BINARY_NAME)).is_file():
                return binary_path
        return None

    @classmethod
    def _install_managed_binary(cls) -> Path:
        server_dir = cls.plugin_storage_path / 'server'
        binary_path = server_dir / BINARY_NAME
        version_file = server_dir / 'VERSION'
        if binary_path.is_file() and version_file.is_file() and version_file.read_text().strip() == VERSION:
            return binary_path
        target = TARGETS.get(f'{sublime.platform()}-{sublime.arch()}')
        if not target:
            raise PluginStartError('Prebuilt tombi binary is not available for this system.')
        archive = f'tombi-cli-{VERSION}-{target}.{"zip" if IS_WINDOWS else "tar.gz"}'
        cls.plugin_storage_path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(cls.plugin_storage_path)) as tmp:
            archive_path = Path(tmp, archive)
            with urllib.request.urlopen(DOWNLOAD_URL.format(version=VERSION, archive=archive)) as response:
                with open(archive_path, 'wb') as f:
                    shutil.copyfileobj(response, f)
            staging_dir = Path(tmp, 'server')
            staging_dir.mkdir()
            _extract_binary(archive_path, staging_dir / BINARY_NAME)
            (staging_dir / 'VERSION').write_text(VERSION)
            shutil.rmtree(server_dir, ignore_errors=True)
            shutil.move(str(staging_dir), str(server_dir))
        return binary_path

    @override
    def on_server_response_async(self, response: ServerResponse) -> None:
        if response['method'] == 'initialize':
            if (session := self.weaksession()) and (source := self._server_sources.get(session.window.id())):
                session.set_config_status_async(source)

    @override
    def on_pre_send_notification_async(self, notification: ClientNotification) -> None:
        if notification['method'] != 'textDocument/didSave':
            return
        uri = notification['params']['textDocument']['uri']
        scheme, path = parse_uri(uri)
        if scheme == 'file' and Path(path).as_posix().endswith(CONFIG_FILENAMES):
            # Defer so that the server receives `didSave` first.
            sublime.set_timeout_async(partial(self._update_config_async, uri))

    def _update_config_async(self, uri: DocumentUri) -> None:
        if session := self.weaksession():
            session.send_request_async(Request('tombi/updateConfig', {'uri': uri}), lambda _: None)

    @uri_handler('tombi')
    def on_open_tombi_uri(self, uri: DocumentUri, flags: sublime.NewFileFlags) -> Promise[sublime.Sheet | None]:
        session = self.weaksession()
        if not session:
            return Promise.resolve(None)
        request: Request[dict[str, str], str | None] = Request('tombi/getBuiltInSchema', {'uri': uri})
        return session.send_request_task(request).then(partial(self._open_built_in_schema, session.window, uri))

    def _open_built_in_schema(
        self, window: sublime.Window, uri: DocumentUri, content: str | None | Error
    ) -> sublime.Sheet | None:
        if not isinstance(content, str):
            window.status_message(f'LSP-tombi: Schema not found: {uri}')
            return None
        view = window.new_file(syntax='Packages/JSON/JSON.sublime-syntax')
        view.set_name(uri)
        view.run_command('append', {'characters': content})
        view.set_scratch(True)
        view.set_read_only(True)
        return view.sheet()


def _extract_binary(archive_path: Path, destination: Path) -> None:
    # Extract only the executable so that no other archive member touches the file system.
    if archive_path.suffix == '.zip':
        with zipfile.ZipFile(archive_path) as zf:
            member = next(name for name in zf.namelist() if name.rsplit('/', 1)[-1] == BINARY_NAME)
            with zf.open(member) as src, open(destination, 'wb') as dst:
                shutil.copyfileobj(src, dst)
    else:
        with tarfile.open(archive_path, 'r:gz') as tf:
            info = next(m for m in tf.getmembers() if m.isfile() and m.name.rsplit('/', 1)[-1] == BINARY_NAME)
            src = tf.extractfile(info)
            assert src
            with src, open(destination, 'wb') as dst:
                shutil.copyfileobj(src, dst)
        destination.chmod(0o755)


class LspTombiSelectSchemaCommand(LspTextCommand):

    def run(self, edit: sublime.Edit) -> None:
        if not self.view.file_name():
            self._status('Save the file before you select a schema')
            return
        if session := self.session_by_name(self.session_name):
            request: Request[dict[str, Any], ListSchemasResponse] = Request('tombi/listSchemas', {})
            session.send_request(request, self._on_schemas_async)

    def _on_schemas_async(self, response: ListSchemasResponse) -> None:
        if not (schemas := response['schemas']):
            self._status('No schemas available')
            return
        items = [
            sublime.QuickPanelItem(schema.get('title') or schema['uri'], schema.get('description', ''), schema['uri'])
            for schema in schemas
        ]
        if window := self.view.window():
            window.show_quick_panel(
                items, partial(self._on_select, schemas), placeholder='Select a schema for the current TOML file')

    def _on_select(self, schemas: list[SchemaInfo], index: int) -> None:
        file_name = self.view.file_name()
        if index < 0 or not file_name or not (session := self.session_by_name(self.session_name)):
            return
        schema = schemas[index]
        params: dict[str, Any] = {
            'uri': schema['uri'],
            'fileMatch': [file_name],
            # Make the selected schema take precedence over catalog schemas.
            'force': True,
        }
        params.update({key: value for key, value in schema.items() if key in ('title', 'description', 'tomlVersion')})
        session.send_notification(Notification('tombi/associateSchema', params))
        self._status(f'Schema "{schema.get("title") or schema["uri"]}" applied')

    def _status(self, message: str) -> None:
        if window := self.view.window():
            window.status_message(f'LSP-tombi: {message}')


class LspTombiRefreshCacheCommand(LspWindowCommand):

    def run(self) -> None:
        if session := self.session():
            request: Request[dict[str, Any], bool] = Request('tombi/refreshCache', {})
            session.send_request(request, self._on_result, self._on_error)

    def _on_result(self, result: bool) -> None:
        if result:
            self.window.status_message('LSP-tombi: Cache refreshed')

    def _on_error(self, error: Any) -> None:
        sublime.error_message(f'LSP-tombi: Failed to refresh cache: {error.get("message", error)}')


class LspTombiShowStatusCommand(LspTextCommand):

    def run(self, edit: sublime.Edit) -> None:
        if session := self.session_by_name(self.session_name):
            request: Request[dict[str, str], GetStatusResponse] = Request(
                'tombi/getStatus', {'uri': uri_from_view(self.view)})
            session.send_request(request, self._on_status)

    def _on_status(self, status: GetStatusResponse) -> None:
        rows = [
            ('TOML', f'{status["tomlVersion"]} ({status["source"]})'),
            ('Config', status.get('configPath') or 'default'),
        ]
        if schema := status.get('schema'):
            rows.append(('Schema', schema['uri']))
        if ignore := status.get('ignore'):
            rows.append(('Ignore', ignore.replace('-', ' ')))
        content = '<br>'.join(f'<b>{escape(label)}:</b> {escape(value)}' for label, value in rows)
        sublime.set_timeout(
            partial(self.view.show_popup, content, sublime.PopupFlags.HIDE_ON_MOUSE_MOVE_AWAY, max_width=800))
