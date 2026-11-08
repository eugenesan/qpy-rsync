# Comparison UI direction

The milestone 1 flat table is temporary scaffolding for process and parser validation.

The target interface is a synchronized two-pane hierarchical tree inspired by Meld and FreeFileSync:

- source tree on the left
- action/direction gutter in the center
- destination tree on the right
- aligned rows for matching relative paths
- placeholders for objects present on one side only
- expandable directories
- changed-only and all-objects modes
- synchronized expansion, selection, sorting, and vertical scrolling
- per-object action control in the center gutter

The comparison plan remains one-way even though both filesystem states are visible.
