"""The flat model must show the same items as the tree model.

The two views are alternatives for the same comparison, so every number the
user reads must match. These tests compare the two models side by side.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
from qpy_rsync.gui.change_filter_proxy import ChangeTreeFilterProxyModel
from qpy_rsync.gui.change_tree_model import ChangeTreeModel
from qpy_rsync.gui.flat_change_model import FlatChangeModel


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def sample_changes() -> list[Change]:
    return [
        Change("docs/a.txt", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f", size=10),
        Change("docs/b.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f", size=20),
        Change("docs/sub/c.txt", ChangeAction.NO_CHANGE, ObjectKind.FILE, "=", size=30),
        Change("pics/d.jpg", ChangeAction.UPDATE_CONTENT, ObjectKind.FILE, ">f", size=40),
        Change("pics/e.jpg", ChangeAction.DESTINATION_ONLY, ObjectKind.FILE, "*d", size=50),
        Change("top.txt", ChangeAction.CREATE, ObjectKind.FILE, ">f", size=60),
    ]


def tree_paths(changes, pattern: str | None = None, actions=None) -> set[str]:
    model = ChangeTreeModel()
    proxy = ChangeTreeFilterProxyModel()
    proxy.setSourceModel(model)
    model.set_changes(changes)
    if pattern is not None:
        proxy.set_path_filter(pattern)
    if actions is not None:
        proxy.set_visible_actions(actions)
    return proxy.visible_paths()


def flat_paths(changes, pattern: str | None = None, actions=None) -> set[str]:
    model = FlatChangeModel()
    model.set_changes(changes)
    if pattern is not None:
        model.set_path_filter(pattern)
    if actions is not None:
        model.set_visible_actions(actions)
    return model.visible_paths()


def test_both_models_show_the_same_items() -> None:
    application = app()
    changes = sample_changes()
    assert tree_paths(changes) == flat_paths(changes)
    model = FlatChangeModel()
    model.set_changes(changes)
    model.deleteLater()
    application.processEvents()


def test_both_models_filter_the_same_way() -> None:
    application = app()
    changes = sample_changes()
    for pattern in ("", "a.txt", "docs", "docs/", ".jpg", "pics/", "*.jpg"):
        assert tree_paths(changes, pattern) == flat_paths(changes, pattern), pattern
    model = FlatChangeModel()
    model.set_changes(changes)
    model.deleteLater()
    application.processEvents()


def test_both_models_apply_the_action_filter_the_same_way() -> None:
    application = app()
    changes = sample_changes()
    for actions in (
        {ChangeAction.CREATE},
        {ChangeAction.UPDATE_CONTENT, ChangeAction.CREATE},
        {ChangeAction.NO_CHANGE},
    ):
        assert tree_paths(changes, None, actions) == flat_paths(
            changes, None, actions
        ), actions
    model = FlatChangeModel()
    model.set_changes(changes)
    model.deleteLater()
    application.processEvents()


def test_the_directory_totals_match_the_tree() -> None:
    application = app()
    changes = sample_changes()
    tree = ChangeTreeModel()
    tree.set_changes(changes)
    flat = FlatChangeModel()
    flat.set_changes(changes)

    def tree_total(path: str) -> tuple[str, str]:
        node = tree.root
        for part in path.split("/"):
            node = next(
                (child for child in node.children if child.name == part), None
            )
            if node is None:
                return ("", "")
        index = tree.index_for_path(path)
        return (
            str(tree.data(index.siblingAtColumn(tree.SOURCE_ITEMS), 0) or ""),
            str(tree.data(index.siblingAtColumn(tree.SOURCE_SIZE), 0) or ""),
        )

    def flat_total(path: str) -> tuple[str, str]:
        index = flat.index_for_path(path)
        return (
            str(flat.data(index.siblingAtColumn(flat.SOURCE_ITEMS), 0) or ""),
            str(flat.data(index.siblingAtColumn(flat.SOURCE_SIZE), 0) or ""),
        )

    for path in ("docs", "docs/sub", "pics"):
        assert tree_total(path) == flat_total(path), path
    tree.deleteLater()
    flat.deleteLater()
    application.processEvents()
