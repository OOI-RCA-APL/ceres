# Changelog

All notable changes are recorded here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/), with an "Unreleased" section collecting
changes as they land. `make release` retitles that section to the version and date and
creates the GitHub release from it, so this file is the only place release notes are
written, and the release workflow refuses a version that has no entry here.

## [Unreleased]

## [0.42.0] - 2026-08-14

**Web Console**

- Build chart and meter widgets from a component's declared particle fields, selected in a
  searchable tree, dragged into a workspace, or created from the context menu.
- Rename value widgets to meters, migrating stored widgets on load.
- Derive a chart's Y axis unit from the plotted fields' declared units when its own unit
  setting is blank.
- Keep the workspace tab strip on screen at both edges of the page, with a toggle that
  shows and hides the workspace content.
- Drag workspaces between the "Shared" and "Private" groups with a copy-or-move choice,
  and edit visibility from "Workspace Settings" behind the same lost-access warning.
- Serve workspaces flagged "Show On Home" to anonymous visitors, redacted, and offer a
  "Log In" button on the signed-out home page.
- Unlock control widget arguments by default and show them in the confirm dialog.
- Offer widget rename on hover, and link procedures and meter widgets to their component
  from the widget context menu.

**API**

- Embed each component's declared particle types in the components listing.

**Engine**

- Derive the particle types a component emits, retrievable with their field schemas.
- Add a `Unit` field marker that publishes a measurement unit in a field's JSON schema.

## [0.41.2] - 2026-08-10

**Fixes**

- Create the directories leading to a configured database file, so a fresh project's
  first run works without preparing them.

**Documentation**

- Rewrite the comments and documentation for clarity, and correct stale claims in the
  development and driver guides.

## [0.41.1] - 2026-08-07

**Fixes**

- Fix engine commands failing to start when installed as `ceres-engine` from PyPI.

## [0.41.0] - 2026-08-07

**Engine**

- Rewrite the core in Rust. The engine, server, record path, and filter compiler are now
  native, while the authoring surface (components, entities, configuration, and the public
  `ceres` API) remains Python and is unchanged.
- Move the Turso database backend to the native core, removing the `pyturso` and
  `sqlalchemy` Python dependencies.

**Documentation**

- Revise the documentation throughout, with the configuration, CLI, HTTP API, and Python
  API references generated from the code.

**CLI**

- Rewrite the CLI in Rust. Most commands are instant now, where every command used to be
  noticeably slow to start. `python -m ceres` remains available everywhere.

**Packaging**

- Publish to PyPI as `ceres-engine`, with pre-built wheels for Linux (x86_64, aarch64),
  macOS (arm64, x86_64), and Windows (x64), for both the standard and free-threaded CPython
  builds.
- Release under the MIT license.

## [0.40.0] - 2026-05-05

- Add `size` parameter to `@packable` decorator for compile-time size assertions
- Add `order` parameter to `@packable` decorator to set `__byte_order__`
- Add `PackedSequence` schema for fixed-length homogeneous binary sequences
- Add docstrings, test suites, and coverage tooling
- Remove `Failure` wrapper, make `Error` inherit from `Exception`
- Revamp docs, replace examples, fix sieve connection filtering

## [0.38.0] - 2026-04-15

**Breaking**
- Rename `Message.content` to `Message.data` to align with particles.
- Rename `_internal` module to `__internal__`.
- Restructure `ceres.data` into a package, split `util` module into various submodules.
- Require Python 3.14+.

**Features**
- Split `ceres/data.py` into a `ceres/data/` package with a new `binary` module providing `PackingSchema`, `PackedTuple`, `PackedModel`, `pack`/`unpack` helpers for struct-style binary serialization.
- Refactor how particles are defined, add `BinaryRegexParticle`.
- Make `DataObject` handle generics like `BaseModel`.
- Add built-in `ceres.concurrency.sleep` function.
- Add `@sieve` decorator to declare sieves as methods, refactor connections into distinct managed objects (#134).

**Fixes**
- Fix parameterless `@sieve`.
- Fix `ConnectionConfig` requiring a `class`, now defaults to `Connection`.
- Fix byte order resolution in `ceres.data.binary` packers.

**Web Console**
- Add pause button to chart widget.
- Replace `TextContent`/`SpecialCharacter` with `DataContent`/`DataToken` in record view.

## [0.37.0] - 2025-10-17

**Web Console**

- Add a new "Button" widget to workspaces, which can be configured to call a component's action with pre-set arguments. The button's color, style and tooltip can all be customized. Closes #117.
- Fix issue where clicking the clear button on a schema form input would not immediately clear the visual text.
- Fix issue where component address inputs in workspaces wouldn't show the current value.

## [0.36.0] - 2025-10-09

**Engine**

- **BREAKING** — Fix database insert of messages containing null bytes. 
  
  *To upgrade you should drop the `ix_messages__content` index in the database, then either restart Ceres or run `ceres database init` to reconstruct the index. Failing to do so will cause slow message searches.*

**API**

- Don't log useless ASGI errors when web socket authentication fails. 

**Web Console**

- Fix wonky dotted border of component status badges when running in Safari.

## [0.35.2] - 2025-09-16

**Web Console**

- Update to `echarts@5.6.0`, removing old, inefficient workaround for appending data while zooming. 
- Make the x-axis of workspace charts scroll linearly with time.
- Update `quasar`, `vue` and related packages to their latest versions, perform required project structure changes.
- Update most other packages to their latest versions, addressing all issues `npm audit` found.
- Run type-checking in `link` task and CI, fix discovered linting issues.

## [0.35.1] - 2025-09-15

**Web Console**

- The last widget in workspace rows will now always grow to the end properly.
- Workspace widget rows can now be split equally into 3 or 5 widgets. This is implemented utilizing 120 subdivisions of space for each row, rather than the previous 100.
- Fix issue where "Working Copy" would sometimes not disappear after committing changes to a workspace.
- Fix drop zone between workspace widgets being too far to the left.

## [0.35.0] - 2025-09-15

**Engine**

- Add `StreamingOutput` and `FileOutput` return types for component queries, allowing them to return a mime-typed data stream or file data from a path, rather than only being able to return JSON serializable objects.
- Add `rtsp` helper to proxy an RTSP URL as a `StreamingOutput` object which can be returned from a query. This requires `ffmpeg` to be installed for the current user in order to re-stream the input RTSP stream as MP4.
- Rename `ceres.stream.Stream` and related classes to `ceres.channel.Channel` instead. This helps separate the concept from byte streams, which are the more commonly encountered meaning in Python. It's also the more commonly used name for the same concept in other languages like `Rust` or `Go`.

**REST API**
- Add API endpoints for calling and retrieving info of component queries and actions specifically, in addition to the generic `procedures` endpoints which already existed.

**Web Console**
- Add `WorkspaceWidgetVideo` to workspaces, allowing users to select any query returning a video-typed `StreamingOutput` or `FileOutput` object to render. In Safari, streaming video uses the `MediaSource` API to stream the video directly into a media buffer, who's URL is then passed to the `video` element as `src`. The reason why is Safari's `video` element doesn't support chunked video responses being sent directly back from an HTTP endpoint, and instead requires the endpoint to support range requests, which doesn't really make sense when streaming live video. This was a pain to figure out, but it works.
- Use a centrally located widget type registry to manage configuration and related components, rather than hard coding a bunch of conditional rendering for each widget type.
- Change schema form inputs to all have obvious clear buttons if the value is allowed to be removed.
- Add "+" button to create a schema form array when the current array value is undefined. A clear button takes its place after being clicked, this effectively works as a toggle.
- Clicking the blue/grey sidebar indicator for schema form inputs no longer toggles (creating initial value or setting undefined) the current value.
- Indicate errors in schema forms using the colored side indicator. If there is an error, the indicator will appear red, and hovering over it will show a tooltip showing what the error is.
- Overall, improve the look and feel of schema forms.
- Only list components with procedures in procedures view widget.

**Development**
- Add `./scripts/host-rtsp.sh` to spin up a looping RTSP stream for testing in development.

## [0.34.1] - 2025-08-06

**General**

- Fix streamed entity queries not freeing memory until completed.

**CLI**

- Fix `--version` flag command being ignored.

## [0.34.0] - 2025-08-05

**General**

- Implement `min_level` and `max_level` filters for logs and alerts.

**Web Console**

- Make it more obvious that record view headers are clickable and can be used to edit filters.

## [0.33.1] - 2025-08-04

**CLI**

- Fix issue with using websocket endpoints from CLI.

## [0.33.0] - 2025-08-01

**Console**

- Reintroduce the ability to export and import workspaces to/from file.
- Make the background of dark mode workspace widgets a bit darker for better contrast.

**CLI**

Fix issue where passing JSON data to some CLI commands would fail.

## [0.32.0] - 2025-07-29

Long time coming with this one. This was originally intended to just be a base implementation of workspaces, but ended up being a much larger update.

Primary Changes

- Implement shared workspaces. 
    - Workspaces are now stored in the database, and can be shared with other users.
    - Doing so has required adding three new tables to the database: `workspaces`, `workspace_memberships` and `workspace_edits`.
    - Users have associated workspace memberships which specify a "workspace role," which can be either `viewer`, `editor`, or `manager`.
        - `viewer`: Can change workspace content (widgets) for themselves, but cannot commit the changes to the shared version.
        - `editor`: Can change workspace content AND commit those changes to the shared version of the workspace.
        - `manager`: Can change and commit workspace content AND settings, including the workspace's name, members, and general permissions. Managers can change the workspace role of any member, can remove members or delete the workspace altogether.
    - Workspaces can specify general access permissions for user roles `viewer`, `operator` or `admin` to allow users with roles meeting the given _user role_ to see and join the workspace as a given _workspace role_.
    - Any user can create workspaces at any time. Creating a new workspace defaults to only allowing access to the current user, IE, it will be private.

Other Changes

- Web Console
    - Many UI elements now look more consistent by using global styles.
    - Added icons to most buttons/menu items.
    - Show leading `@` for components that are direct children of the root component in the sidebar.
    - Show leading `.` for components that are children of the above.
    - Sidebar component control menu (the one with actions like "Stop" / "Start," etc.) now hides unnecessary actions when said action would do nothing, indicates how many components would be affected by multi-component actions and has colored icons to make things more readable and prevent mistakes.
    - Many other small design tweaks.
    - Workspace widgets now snap their sizes to ~10px increments. This allows users to easily make widgets the same size without fiddling too much, and prevents floating point weirdness in workspace data to cause the UI to show the workspace as modified when it really hasn't been.
    - Add "value" widget to display a single value from the latest particle matching a query.
    - Fix infinite looping API calls in record view which were triggered under certain conditions.

- Engine / API
    - Entity filters now include "and" and "or" fields to allow more complex queries.
    - Fix bug where eager tasks and 

- CLI
    - Added `database shell` command to open `sqlite3` or `psql` on the current database.
    - Remove `database dump` and `database load` commands. These are now handled by the dedicated entity `load` and `select` commands.

## [0.31.0] - 2025-05-22

- Show affected components when running start, stop, enable, disable, up and down commands on CLI.

## [0.30.0] - 2025-05-22

- Implement `TCPServer` and `UNIXSocketServer`.
- Implement `UNIXSocketConnection`.
- Refactor and revise connections, use events instead of logging.
- Use `anyio` for all built-in server and connection implementations.
- Fix unrelated error where pruning deletes weren't executing properly.
- Generate kebab-case aliases for `DataObject` and `ValidatedDataclass`.

## [0.29.1] - 2025-05-21

- Ensure connections disconnect when EOF is received over the stream.
- For connections, delay by initial reconnect scheduler delay after disconnecting before doing a reconnect.
- Explicitly yield to the event loop during connection processing.

## [0.29.0] - 2025-05-16

- Add `Event.level` with default values for all built-in events.
- Make logging configuration better and more flexible, adding minimum levels to log for events and alerts and minimum levels to output to stderr and save to the database.
- Keep workspace chart tooltips in web console contained within chart bounds, preventing them from being partially obscured by the canvas edges.

## [0.28.1] - 2025-05-14

- Fix missing `timespan` default for workspace chart query in web console.

## [0.28.0] - 2025-05-14

- Implement time-bucketing based subsampling for records, but most importantly, particles, and use it for rendering workspace charts. 

  Record filters now support the following subsampling options:

  - `subsample_every`: Subsample results by selecting at most one record per this interval of time.
  - `subsample`: Subsample results by selecting at most one record per `subsample` divisions of the total time range specified by the filter.
  - `subsample_select`: Specify which record to choose per subsampled time bucket specified by `subsample_every` and `subsample`. If unspecified or `None`, this will default to `SubsampleSelect.FIRST`.

## [0.27.2] - 2025-05-12

- Remove usage of `AbstractEventLoop.add_signal_handler`, which can't be used on Windows.

## [0.27.1] - 2025-05-09

- Remove `launchd` package dependency. It's not necessary, is unmaintained, as was causing very strange errors to be thrown when using `ceres service` commands.

## [0.27.0] - 2025-05-08

- Implement CLI `load` command for all entity types. Entities can be loaded into the database from either JSON/JSONL files or CSV.
- Add `--output` option to CLI data commands.
- Allow specifying fields as position arguments for `select` and `follow` in the CLI.

## [0.26.2] - 2025-05-08

- Fix `cancelling` `wait_any` not cancelling after the call itself is cancelled.
- Handle `ceres run --watch` in a more robust way.
- Fix slow `EmailStr` validation for users.

## [0.26.1] - 2025-04-14

- Fix possible exception in `Address.parent`.
- Correctly rename "Code" to "Type" and "Info" to "Data" in dispatcher emails.

## [0.26.0] - 2025-04-07

- Allow specifying `--data-format json` to output newline delimited JSON, and `--data-format csv` to output CSV data, when running the `select`, `create`, `update`, and `delete` CLI commands. This option defaults to the `json` format (JSONL).

## [0.25.0] - 2025-04-03

- Add CLI `follow` commands to live-print new messages, particles, alerts and logs. For example, to see the latest messages being received/sent, run `ceres messages follow`.

## [0.24.4] - 2025-04-03

- Fix component subscriptions exiting immediately, causing component UI elements to appear to never load in console.

## [0.24.3] - 2025-04-02

- Only access Pydantic's `BaseModel.model_fields` on class instances to avoid deprecation warnings.

## [0.24.2] - 2025-04-02

- Fix issue where having extra cookies while accessing the API over HTTP/2 could cause authentication to fail. See https://github.com/encode/starlette/discussions/2916.

## [0.24.1] - 2025-04-01

- Fix change password dialog in web console.

## [0.24.0] - 2025-03-20

- Drop `hypercorn` in favor of `granian`, a webserver written in Rust that's currently the fastest available ASGI server. Additionally, it's actively maintained and getting better, and faster, over time. Once Granian supports utilizing multiple threads and we're able to support free-threaded Python, this should give us another pretty nice performance boost. https://github.com/emmett-framework/granian
- Use a random port instead of a Unix socket for CLI operations that communicate with the server over HTTP. This is done because Granian doesn't support Unix sockets yet. See https://github.com/emmett-framework/granian/issues/97.
- Fix issue where server websocket endpoints were not actually being closed upon request from the client and only closing the browser tab would successfully kill running websocket endpoints.

## [0.23.0] - 2025-02-14

- Allow `enable`, `disable` and `status` commands when server is offline.
- Don't enable ancestor components on `enable`.
- Fix how enabled components are started by the engine.
- Add `/api/alive` endpoint to check if the server is running.
- Add `VariableFilter.value`.

## [0.22.5] - 2025-02-13

- Fix user create page.

## [0.22.4] - 2025-02-13

- Fix workspace charts not fully rerendering after changing between light and dark mode.
- Fix error when "Timespan" in workspace chart is empty.
- Fix blank users page.

## [0.22.3] - 2025-02-12

- Yield to the event loop while running iterated queries in entity managers. This prevents blocking the main thread when retrieving large numbers of database entities at once.
- Fix issue in web console where updating configuration on component UI displays would sometimes work incorrectly.

## [0.22.2] - 2025-02-11

- Allow `MessageFilterArgs.address` to be a `str`.

## [0.22.1] - 2025-02-11

- Fix `--version` flag in CLI.

## [0.22.0] - 2025-02-11

- Refactor, improve and test entity managers and filters.
- Rename `log_entries` table to `logs`.
- Add `log` and `alert` as synonyms for `log` and `alerts` in `Node`.
- Autogenerate simple entity API routes.
- Use `defer_build=True` via the `DeferBuild` mixin on most in-library instances of `DataObject` to improve startup performance.
- Move manager classes into the same module as their related objects.
- Refactor manager classes, use consistent base classes and protocols.
- Move classes in `ceres.role` to just be under `ceres`.
- Cascade user deletes and updates to settings.
- Fix issue where imported workspaces would sometimes immediately disappear.
- Allow creating components with name as first positional argument.

## [0.21.2] - 2025-01-23

- Fix `container` retrieval in `_execute_component_actions`.

## [0.21.1] - 2025-01-23

- Fix `users create` command using `--data.` prefix for user fields.

## [0.21.0] - 2025-01-22

- Expose `cancel`, `concurrently`, `wait_any`, and `wait_all` in `ceres.util`.

## [0.20.0] - 2025-01-21

* Switch to `pydantic-settings` for CLI instead of `typer`.
* Fix issue with websockets preventing server shutdown.

## [0.19.0] - 2025-01-14

- Refactor `parent` and `engine` logic for components to only allow one "container" node for each. This node is available at `ComponentSystem.container`.
- Allow `ComponentSystem.detach()` to detach a component from its container, whether that's another component or an engine.
- Attach components to containing engine/component during initial creation to avoid missing initial log messages. This is done through the new `__with_container__` parameter on components.
- Add `Engine.attach` method.
- Remove `graceful_timeout` from HTTP server, which was causing shutdown to delay 3 seconds when websockets were open.
- Fix issue with reload not detecting changes in some component configuration fields.
- Add `__slots__` to `ComponentSystem` and `Engine`.

## [0.18.0] - 2025-01-13

- Implement "pruners": recurring jobs that delete records from the database on a schedule.
    
    ```yaml
    pruners:
      - name: log-pruner
        prunes: log-entry
        schedule: 5s
        filter:
          min_age: 30d
    ```

## [0.17.0] - 2025-01-07

- Fix dependency specifiers to actually use the latest compatible versions of libraries.
- Use `asyncio.eager_task_factory` in created event loop by default.
- Expose `ensure_event_loop` in `ceres.util`.
- Add `uvloop` and `eager` options to `ensure_event_loop` which both default to `True`.

## [0.16.1] - 2025-01-04

- Optimize SQL queries generated by entity filters.

## [0.16.0] - 2025-01-03

- Fix component cancellation issues caused by usage of `asyncio.gather` which does not wait for cancelled tasks when the containing coroutine is cancelled. A `concurrently` helper method has been added which does essentially the same thing as gather, but runs tasks in a `TaskGroup` to handle cancellation properly.
- Don't make SQLAlchemy entity classes Pydantic dataclasses. An update to Pydantic has caused this to stop working.
- Allow `StreamReader` to be used across different threads/event loops. This is necessary for logging to work properly from camera control scripts, which run in a separate thread.
- Use consistent plural naming of entities in REST and CLI APIs. Rename `/log-entries` router/subcommand to just `/logs`.
- Refactor how loggers are handled. Add `get_logger` function, allow converting `Level` to and from Python's log level integers.
- Allow query and action methods to be non-async. Technically, this was already possible, but type checking did not accept it.

## [0.15.1] - 2024-11-22

- Use `uv` as package manager instead of Python.
- Improve performance of appending to workspace record views.
- Slightly reduce console bundle size by using `lodash-es` rather than `lodash`.
- Remove unintended `venv` and `venvPath` from `pyright` configuration in `pyproject.toml`.

## [0.15.0] - 2024-11-21

- Add "particle" and "sieve" systems.
- Rename `Alert.code` to `Alert.type` and `Alert.info` to `Alert.data`.
- Remove unused `search` and `search_fields` from filters.
- Add `timespan`, `after_hour`, `before_hour`, `after_minute`, and `before_minute` filter fields to record filters.
- Rename disconnect and reconnect settings for `Connection` to `disconnect_on` and `reconnect_on`.
- Allow passing cron or timedelta expressions as schedules in configuration.
- Allow specifying query arguments in database configuration.
- Use `JSON` instead of `JSONB` in database to preserve key order, use mapped columns rather than strings where possible.
- Add filter fields for searching JSON columns as text.
- Add GET routes for single record types in API.
- Add configurable zstd, brotli and gzip compression to web server.
- Allow configuring web server CORS settings.
- Add "Chart" widget to workspaces.
- Compile web console to single JS and CSS files for better caching in low bandwidth scenarios.
- Add syntax highlighting to code-like fields in web console.
- Add request batching to web console to improve performance.
- Various other bug fixes and small improvements all-around.

## [0.14.0] - 2024-10-07

- 991b692 Add "workspaces" to web console.

## [0.13.3] - 2024-06-19

- 55cc38e Make `count` command faster for common cases

## [0.13.2] - 2024-06-18

- a945d95 Don't use BRIN index with Postgres due to Hydra incompatibility

## [0.13.1] - 2024-06-18

- fea0686 Fix console parsing of `Config` model on reload

## [0.13.0] - 2024-06-18

- 3b70f25 Add `BaseEntityManager.select`, use `model_construct` for better performance
- a6abf8a Move `tool.ruff.lint.ignore` to its own `pyproject.toml` section
- 3c2dcf0 Use constant `TypeAdapter(Any)` for `jsonify` and `simplify`
- 6de5d1c Add full `write` args to `write_json`, add `color` argument
- 6c923ea Remove `black`, use `ruff format`
- 6b4223f Fix variable `address` not being searchable
- 6b11473 Make `order` field nullable for CLI
- 01631c9 Remove duplicate `order` field from `VariableFilter`
- c408141 Make `Database` importable from `ceres.database`
- 65fa6e8 Type check `order` and `search_field` arguments, move base classes under `_internal`
- 1a2c785 Allow arbitrary entity ordering
- fc01cd3 Make `use_database()` a context manager
- 6249949 Allow using `Database` as context manager
- 21703d4 Replace `BaseRecordFilter.within` with `max_age` and add `min_age` field, remove `StatisticsFilter.within`
- 642dd63 Disallow extra arguments to `BaseFilter`
- 79e3012 Fix record ordering
- 26da0d1 Check that configured `dashboard` components exist
- 18d548b Make address objects pickleable
- 9939c3a Remove `id` from `Variable`
- b6729da Fix missing `VariableFilter` `address` field
- 4737982 Change item `order` values to `oldest` and `newest`
- fa914a3 Add `variable` CLI router, refactor CLI code, don't print engine logs unnecessarily
- 06bf833 Add `Variable` entity type, remove `Store`
- 0d58d18 Use non-greedy wildcard for default line-separated `Connection` regex pattern
- ac875e9 Make `Address` and its superclasses not inherit from `str`
- 27aab00 Remove `extras = ["all"]` from `typer` dependency

## [0.12.0] - 2024-06-13

- Fix missing `StoreRow.id` default value on insert. This caused enable/disable to not work if the `stores` table was using the new schema.
- Use trigram indexes for text-searched database columns when using Postgres.
- Use gin indexes for timestamp columns when using Postgres. 
- Use `ClassVar` for entity `__tablename__` and `__abstract__` in entity row classes so `pyright` doesn't think they're required arguments.

## [0.11.0] - 2024-06-11

- Fix `enable` and `disable`.

## [0.10.0] - 2024-06-11

- Fix dependency specifications.
- Improve CLI startup speed for some commands.
- Refactor and fix issues with `Engine.reload()`.
- Allow creating a `Component` (and all subcomponents) from a `ComponentConfig` using `ComponentConfig.create()`.
- Validate `ComponentConfig` `class` and `arguments` automatically.
- Refactor config related objects.

## [0.9.0] - 2024-06-06

**Major Changes**

*Breaking*

- Require Python 3.12 or higher.

- All ceres-related functionality of components is now available on `Component.system` rather than being directly on the components themselves. This has been done primarily to avoid naming conflicts between user-defined attributes and methods and ceres-defined ones. For example, in a component, the original `self.name` is now available at `self.system.name`, and any component which wants to define its own `name` field for configuration can do so.

- Events, messages, alerts, log entries and statistics for components and the engine are manageable using manager instances. For instance, to emit an event from a component, call `self.system.events.emit(Event, **kwargs)`, and to query messages, call `await self.system.messages.get_all(limit=50)`. Entity managers are also available on `Database`.

- Component jobs are now managed from `Component.system.jobs`.

- The `@on` decorator has been renamed to `@listener`.

- `Connection` now supports the following `arguments`:
  - `regex`:  A `bytes` regex pattern which will be used to extract messages from a data buffer. Upon finding a match, all data in the buffer before the end of the match is dropped.
  - `regex_flags`: `RegexFlags` used for compiling `regex`. Defaults to `"MS"` (MULTILINE | DOTALL).
  -  `buffering` settings:
    - `read`: How many bytes to read from the incoming stream and into the buffer at a time. Defaults to 1 KB.
    - `limit`: The maximum number of bytes to keep appending to the buffer before dropping `drop` bytes from the beginning. Defaults to 100 KB.
    - `drop`: The number of bytes to drop from the beginning of the buffer when the buffer grows larger than `limit`. If multiple drops are necessary to bring the buffer down to `limit` bytes, the minimum *multiple* of `drop` bytes will be dropped from the beginning of the buffer.

*Internal*

- References and events should work more consistently now.
- Many types and methods are now imported lazily to cut down on import times. This is done through the use of the `ceres._internal.lazy.lazy_imports` context manager.
- Use `from __future__ import annotations` whenever possible to reduce import times and avoid imports for type hinting. This is especially handy due to the lazy importing of types.

## [0.8.0] - 2024-03-06

- Change `ceres.ui.Value` to `ceres.ui.Text`.
- Add `css_style` and `css_class` fields to all `Element` types.
- Add `ceres.ui.HTMLElement` to `Element` types to render raw HTML.
- Allow rendering multiple dashboard components by passing a list of addresses to `console.dashboard`.
- Add `azip_latest` to `ceres.internal.utilities` until we can figure out a better way to handle its use case.

Fixes

- Fix some typing issues on latest Pyright.
- Fix issue with `DatabaseFilter.matches` not matching certain some strings to `search`.

## [0.7.0] - 2024-02-28

- Implement users and authentication.
- Implement coarse permissions levels, including admin, operator and viewer.
- Add additional CRUD commands and endpoints for both API and CLI, including the ability to create, retrieve, update and delete users.
- Overhaul error handling using `Failure` exception type.
- Support HTTP-2 and HTTP-3.
- Fix issue where left sidebar could be downsized enough to disappear entirely.

## [0.6.3] - 2024-01-19

- Fix `eat_pattern` not advancing parser correctly.

## [0.6.2] - 2023-11-21

- Escape database URLs properly.
- Set defaults for Postgres `host` and `port`.

## [0.6.1] - 2023-11-14

- Import `validate_call` from Pydantic root module due to breaking rename.

## [0.6.0] - 2023-11-07

- Replace `ClassPath` with Pydantic V2's `ImportString`.
- Export standard components from root module.
- Remove `ceres.standard` and move all classes into base modules.
- Run enabled subcomponents when a component is started.

## [0.5.1] - 2023-11-06

- Fix chart resizing.

## [0.5.0] - 2023-11-06

- Allow rendering a specific component as the dashboard.
- Allow specifying a `favicon`.
- Allow changing page `title` of the console, which will change the header and tab name.

## [0.4.0] - 2023-10-25

- Use `0.0.0.0` as default server host.
- Show connected/disconnected status in console, add animated status display.
- Fix `run` command not working without selector.

## [0.3.0] - 2023-10-25

- Allow passing one or more selectors to `ceres run` to start components immediately. For example, you can now run `ceres run all` to start all components `ceres run driver connection` to just start those components.
- Remove now redundant `--all` option for `ceres run`.
- Fix `Address.as_absolute`.

## [0.2.0] - 2023-10-24

- Allow bare `"all"` as an address selector. Disallow it as a component name or address.

## [0.1.2] - 2023-10-24

- Fetch version number from package metadata or `pyproject.toml` as a backup.
- Allow keyword-only arguments in procedures.
- Rename `args` to `arguments` in `ComponentConfig`, `Loader`, and procedure related code.

## [0.1.1] - 2023-10-23

* Move `crabee` and `a3` subprojects into their own repositories. 
* Change package location to the repository root so `subdirectory` is no longer required when specifying `ceres` as a dependency.

## [0.1.0] - 2023-10-23

**Full Changelog**: https://github.com/OOI-RCA-APL/ceres/commits/0.1.0
