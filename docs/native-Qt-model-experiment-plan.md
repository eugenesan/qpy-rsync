# qpy-rsync Native Qt Model Migration Study

## Goal

Reduce the remaining 12-23 second UI rebuild costs observed on 500k-1.2M object comparisons by moving the hot model/view layer out of PySide and into native Qt/C++ while preserving as much of the existing Python application, tests, services, and synchronization logic as possible.

---

# Executive Summary

Profiling indicates that:

- Parser optimization helped.
- Filter optimization helped.
- Plan optimization helped.
- Native nanobind kernels helped microbenchmarks.
- End-to-end UI performance remained dominated by Qt model/view work.

The remaining bottleneck appears to be:

- QAbstractItemModel resets
- QModelIndex generation
- data() callbacks
- row mapping
- view invalidation
- repaint scheduling
- Python↔Qt boundary traffic

The proposed architecture therefore moves only the model layer into native Qt.

The Python application remains the orchestration layer.

---

# Recommended Architecture

## Keep in Python

These areas are not hot enough to justify porting.

### MainWindow

Keep:

- MainWindow
- dialogs
- confirmation views
- filter editor
- startup options
- settings
- logging

### Services

Keep:

- CompareService
- InventoryService
- SyncService
- PlanValidationService

### Domain logic

Keep:

- SyncProfile
- ExecutionGate
- BackupOptions
- validation
- rsync command generation

### Tests

Keep all Python unit tests.

Native components should expose a Python API which existing tests can consume.

---

# Move to Native C++

## FlatChangeModel

Port:

- row storage
- visibility flags
- filtering state
- fold state
- summary aggregates
- QModelIndex generation
- QAbstractTableModel implementation

This is expected to be the largest win.

---

## OverviewModel

Port:

- OverviewNode
- hierarchy construction
- aggregate propagation
- sorting
- model implementation

The current eager construction of ~30k nodes should become fully native.

---

## Decision Store

Port:

- explicit decisions
- inheritance walk
- subtree reset
- undo history
- redo history

Current implementation repeatedly moves large amounts of Python state.

Holding decisions beside the model eliminates this traffic.

---

## Filtering Engine

Port:

- glob matching
- folded-name matching
- visibility computation
- aggregate generation

Filtering already has native prototypes.

Move those algorithms beside the native model.

---

# Data Ownership

## Critical rule

The dataset must be owned by C++.

Do NOT let Python continue owning:

- Change objects
- visibility arrays
- action arrays
- path arrays

while Qt queries a native model.

That would keep the boundary traffic.

---

## Native storage

Suggested layout:

```cpp
struct ChangeRow {
    uint32_t parent;
    uint32_t firstChild;
    uint32_t childCount;

    uint32_t flags;

    QString path;
    QString name;

    int64_t size;

    uint8_t action;
    uint8_t kind;
};
```

Store rows in:

```cpp
std::vector<ChangeRow>
```

or:

```cpp
std::pmr::vector<ChangeRow>
```

for allocator flexibility.

---

# Python/C++ Boundary

## One-time transfer

Preferred flow:

```text
CompareService
    ↓
Python parser
    ↓
list[Change]
    ↓
NativeChangeStore.import_changes()
    ↓
C++ owns everything
```

Transfer once.

Never query Python per row afterwards.

---

## Bad design

Avoid:

```text
Qt View
 ↓
Native Model
 ↓
Python object
 ↓
return field
```

for every visible row.

That reproduces the current overhead.

---

# Native Library Shape

## Single extension module

Recommended:

```text
qpy_rsync_native
```

Containing:

```text
NativeChangeStore
NativeFlatChangeModel
NativeOverviewModel
```

---

## Build system

Recommended:

```text
CMake
+ nanobind
```

Keep existing experiment infrastructure.

Alternative:

```text
Shiboken
```

but substantially more work.

---

# Control Flow

## Compare

Current

```text
CompareService
 ↓
set_changes
 ↓
Python model rebuild
```

Target

```text
CompareService
 ↓
import_changes()
 ↓
native rebuild
 ↓
modelReset()
```

Only one boundary crossing.

---

## Filtering

Current

```text
Python loop
 ↓
aggregates
 ↓
Qt refresh
```

Target

```text
Python UI event
 ↓
native set_filter()
 ↓
native recompute
 ↓
Qt refresh
```

---

## Overview

Current

```text
changes_updated signal
 ↓
Python tree build
```

Target

```text
native model emits ready
 ↓
overview refreshes directly
```

---

# Python API

Suggested API:

```python
store = NativeChangeStore()

store.import_changes(changes)
store.set_filter(pattern)
store.set_show_excluded(True)
store.reset_decision(path)

summary = store.summary()
```

MainWindow should interact only with this surface.

---

# Communication Pattern

No subprocesses.

No IPC.

No sockets.

No gRPC.

The native model should be loaded into the Python process as a shared library:

```text
libqpy_rsync_native.so
```

loaded by:

```python
import qpy_rsync_native
```

Everything runs in-process.

---

# Threading

Keep current service threading.

CompareService remains responsible for:

```text
rsync execution
parsing
```

The resulting dataset is then handed to native storage.

The UI thread continues owning:

```text
Qt widgets
Qt models
Qt views
```

Do not manipulate Qt models from worker threads.

---

# Migration Plan

## Phase 1

Create NativeChangeStore.

Move:

- row storage
- filtering
- decisions
- aggregates

No Qt model yet.

Benchmark transfer cost.

---

## Phase 2

Implement NativeFlatChangeModel.

Keep existing UI.

Replace existing FlatChangeModel only.

Benchmark:

- compare
- hide excluded
- show unchanged
- reset decisions

---

## Phase 3

Implement NativeOverviewModel.

Retire Python OverviewModel.

Measure initial build.

---

## Phase 4

Move plan summary generation.

Current:

```text
3-5 seconds
```

Target:

```text
under 500 ms
```

---

# Expected Gains

Likely improvements:

| Component | Current | Target |
|------------|---------:|---------:|
| plan rebuild | 3.6-4.6 s | <0.5 s |
| overview build | 2.1-2.5 s | <0.5 s |
| model rebuild | 12-23 s | 2-8 s |

The largest uncertainty remains Qt view invalidation itself.

Even a native model may not reach FreeFileSync numbers.

---

# Why FreeFileSync Still Wins

Likely reasons:

- Entire model layer is native.
- Entire view layer is native.
- No Python boundary.
- wxWidgets implementation characteristics.
- Highly optimized memory layout.
- Years of specialized tuning around huge datasets.

Matching FreeFileSync exactly may require a full native rewrite.

However a native model layer offers the highest ROI before considering that step.
