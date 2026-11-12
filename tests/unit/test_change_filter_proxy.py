from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
from qpy_rsync.gui.change_filter_proxy import ChangeTreeFilterProxyModel
from qpy_rsync.gui.change_tree_model import ChangeTreeModel


def _change(path: str, kind: ObjectKind = ObjectKind.FILE) -> Change:
    return Change(path, ChangeAction.UPDATE_CONTENT, kind, ">f.st......")


def _proxy() -> ChangeTreeFilterProxyModel:
    model = ChangeTreeModel()
    model.set_changes(
        [
            _change("docs", ObjectKind.DIRECTORY),
            _change("docs/guide.txt"),
            _change("docs/notes.md"),
            _change("src/app.py"),
            _change("src/README"),
            _change("numbers/12345"),
        ]
    )
    proxy = ChangeTreeFilterProxyModel()
    proxy.setSourceModel(model)
    return proxy


def _top(proxy: ChangeTreeFilterProxyModel):
    return proxy.index(0, 0)


def _root_names(proxy: ChangeTreeFilterProxyModel) -> set[str]:
    total = _top(proxy)
    return {
        proxy.data(proxy.index(row, 0, total))
        for row in range(proxy.rowCount(total))
    }


def test_plain_text_matches_name_and_keeps_ancestor() -> None:
    proxy = _proxy()
    proxy.set_path_filter("guide")
    assert _root_names(proxy) == {"docs"}
    docs = proxy.index(0, 0, _top(proxy))
    assert proxy.rowCount(docs) == 1
    assert proxy.data(proxy.index(0, 0, docs)) == "guide.txt"


def test_shell_glob_matches_names() -> None:
    proxy = _proxy()
    proxy.set_path_filter("*.py")
    assert _root_names(proxy) == {"src"}
    src = proxy.index(0, 0, _top(proxy))
    assert proxy.rowCount(src) == 1
    assert proxy.data(proxy.index(0, 0, src)) == "app.py"


def test_star_shows_all_and_period_matches_names_containing_period() -> None:
    proxy = _proxy()
    proxy.set_path_filter("*")
    assert _root_names(proxy) == {"docs", "numbers", "src"}
    proxy.set_path_filter(".")
    assert _root_names(proxy) == {"docs", "src"}
    proxy.set_path_filter("")
    assert _root_names(proxy) == {"docs", "numbers", "src"}


def test_trailing_slash_includes_full_directory_contents() -> None:
    proxy = _proxy()
    proxy.set_path_filter("docs/")
    assert _root_names(proxy) == {"docs"}
    docs = proxy.index(0, 0, _top(proxy))
    assert {proxy.data(proxy.index(row, 0, docs)) for row in range(proxy.rowCount(docs))} == {
        "guide.txt",
        "notes.md",
    }
