# Ceres

A Python framework for building instrument driver systems with real-time data
acquisition, processing, and management.

## Development

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```
make install
```

### Testing

```
make test
```

### Coverage

```
make coverage
```

| Module | Coverage |
|---|---|
| `ceres/address.py` | 94% |
| `ceres/alert.py` | 92% |
| `ceres/channel.py` | 82% |
| `ceres/component.py` | 73% |
| `ceres/concurrency.py` | 91% |
| `ceres/config.py` | 64% |
| `ceres/connection/__init__.py` | 57% |
| `ceres/connection/buffer.py` | 80% |
| `ceres/connection/source.py` | 87% |
| `ceres/connection/splitter.py` | 100% |
| `ceres/connectivity.py` | 100% |
| `ceres/constants.py` | 100% |
| `ceres/data/__init__.py` | 100% |
| `ceres/data/binary.py` | 91% |
| `ceres/data/converters.py` | 100% |
| `ceres/data/object.py` | 77% |
| `ceres/data/types.py` | 99% |
| `ceres/data/uuid.py` | 77% |
| `ceres/database/__init__.py` | 100% |
| `ceres/database/database.py` | 74% |
| `ceres/database/enums.py` | 100% |
| `ceres/directory.py` | 93% |
| `ceres/dispatcher.py` | 65% |
| `ceres/engine.py` | 32% |
| `ceres/entity.py` | 48% |
| `ceres/error.py` | 94% |
| `ceres/event.py` | 95% |
| `ceres/interface.py` | 100% |
| `ceres/item.py` | 90% |
| `ceres/job.py` | 41% |
| `ceres/level.py` | 75% |
| `ceres/loaded.py` | 55% |
| `ceres/logs.py` | 78% |
| `ceres/message.py` | 94% |
| `ceres/node.py` | 78% |
| `ceres/notifier.py` | 100% |
| `ceres/particle.py` | 89% |
| `ceres/paths.py` | 26% |
| `ceres/pruner.py` | 45% |
| `ceres/record.py` | 89% |
| `ceres/reference.py` | 64% |
| `ceres/rtsp.py` | 29% |
| `ceres/schedule.py` | 96% |
| `ceres/server.py` | 66% |
| `ceres/setting.py` | 97% |
| `ceres/sieve.py` | 99% |
| `ceres/statistics.py` | 61% |
| `ceres/status.py` | 100% |
| `ceres/tasklet.py` | 76% |
| `ceres/timing.py` | 99% |
| `ceres/ui.py` | 90% |
| `ceres/user.py` | 94% |
| `ceres/variable.py` | 83% |
| `ceres/version.py` | 39% |
| `ceres/workspace.py` | 92% |
| **Total** | **78%** |

### Linting

```
make lint
```

### Formatting

```
make fix
```
