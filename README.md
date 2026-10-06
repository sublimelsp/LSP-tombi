# LSP-tombi

This is a helper package that starts the [Tombi](https://tombi-toml.github.io/tombi) TOML language server for you.

Tombi gives formatting, linting, completion, hover and schema validation for all TOML files. It uses the [JSON Schema Store](https://www.schemastore.org/) catalog, so files like `pyproject.toml`, `Cargo.toml` and many others get schema support automatically.

## Installation

1. Install [LSP](https://packagecontrol.io/packages/LSP) via Package Control.
2. Install [LSP-tombi](https://packagecontrol.io/packages/LSP-tombi) via Package Control.

The package downloads the `tombi` binary from GitHub releases when the server starts for the first time. If the workspace folder has a `.venv` with `tombi` installed (for example with `uv add --dev tombi`), the package uses that binary instead.

To use a different binary, change the `command` setting:

```jsonc
{
	"command": ["/absolute/path/to/tombi", "lsp"],
}
```

## Applicable files

This language server operates on views with the `source.toml` base scope.

## Configuration

Open `Preferences: LSP-tombi Settings` from the Command Palette to edit the global settings.

Configure Tombi for your project in a `tombi.toml`, `.tombi.toml` or in the `[tool.tombi]` table of `pyproject.toml`. See the [Tombi documentation](https://tombi-toml.github.io/tombi/docs/configuration) for all options. When you save one of these files, the server loads the new configuration.

You can also give editor-level config in the `settings.tombi` object of the LSP-tombi settings. It uses the same keys as `tombi.toml`.

## Formatting

Tombi supports formatting of the document.

- To format the file, run `LSP: Format File` from the Command Palette.
- To format each time you save, set `"lsp_format_on_save": true` in the LSP settings. To do this only for TOML files, add the setting to the syntax-specific settings (`Preferences > Settings - Syntax Specific`) of a TOML file.

Configure the formatter in the `[format.rules]` table of the Tombi config, for example `indent-width` or `line-width`. See the [configuration documentation](https://tombi-toml.github.io/tombi/docs/configuration) for all rules. Tombi does not use the `tab_size` and `translate_tabs_to_spaces` settings of Sublime Text.

By default, Tombi sorts table keys and array values in the order that the JSON Schema of the file gives (for example in `Cargo.toml` and `pyproject.toml`). To stop this, see [Auto Sorting](https://tombi-toml.github.io/tombi/docs/formatter/auto-sorting).

## Semantic highlighting

Tombi gives semantic tokens for table names, keys, values and `# tombi:` comment directives. To use them, set `"semantic_highlighting": true` in the LSP settings. The `semantic_tokens` setting of LSP-tombi gives the scopes for the custom token types (`table`, `key`, `boolean`, `offsetDateTime`, `localDateTime`, `localDate` and `localTime`). The default scopes are the same as the scopes of the TOML syntax. To change a color, add a color scheme rule for `meta.semantic-token.<token-type>` (all lowercase), for example `meta.semantic-token.table`.

## Commands

| Command palette entry | Description |
| --- | --- |
| `LSP-tombi: Select Schema` | Select a schema from the catalog and apply it to the current file. |
| `LSP-tombi: Refresh Cache` | Remove the cached schemas and catalogs, and fetch them again. |
| `LSP-tombi: Show Status` | Show the TOML version, the config file and the schema for the current file. |

## Alternative to LSP-pyproject

[LSP-pyproject](https://packagecontrol.io/packages/LSP-pyproject) operates only on `pyproject.toml`. Tombi operates on all TOML files, and it also validates `pyproject.toml` with its schema. If you install both packages, you get two sets of diagnostics for `pyproject.toml`. In that case, disable one of them.
