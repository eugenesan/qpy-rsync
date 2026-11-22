import time
from PySide6.QtWidgets import QApplication, QTableView, QTreeView
from qpy_rsync.core.changes import Change, ChangeAction, ObjectKind
from qpy_rsync.backend.rsync_parser import ParseResult
from qpy_rsync.services.compare_service import CompareResult
from qpy_rsync.gui.main_window import MainWindow

app=QApplication([])
w=MainWindow(); w.source_edit.setText('/src/'); w.destination_edit.setText('/dst/')
w._active_profile=w._profile(); w._baseline_profile=w._profile()
N=520000
changes=[Change(f'd{i%30000}/f{i}.txt',
                ChangeAction.CREATE if i%3 else ChangeAction.UPDATE_CONTENT,
                ObjectKind.FILE, '>f', i%1000) for i in range(N)]
def timed(label, fn):
    t=time.perf_counter(); r=fn(); app.processEvents()
    print(f'{label}: {time.perf_counter()-t:.2f}s', flush=True); return r
timed('full _comparison_finished 520k', lambda: w._comparison_finished(CompareResult(ParseResult(changes,[]),'',0)))
v=w._hybrid_view
tabs=sorted(v.widget.findChildren(QTableView), key=lambda t:t.x())
src,act=tabs[0],tabs[1]
timed('decision toggle (file)', lambda: v.set_decision_by_path('d1/f1.txt',2))
timed('undo decision', lambda: w.comparison.undo_decision())
timed('folder subtree exclude', lambda: v.set_decision_by_path('d2',2))
timed('folder subtree undo', lambda: w.comparison.undo_decision())
timed('sort by size', lambda: src.horizontalHeader().setSortIndicator(2, __import__('PySide6.QtCore',fromlist=['Qt']).Qt.SortOrder.AscendingOrder))
timed('fold folder', lambda: v.set_collapsed('d3',True))
timed('expand folder', lambda: v.set_collapsed('d3',False))
unchanged=[Change(f'u{i}/f{i}.txt',ChangeAction.NO_CHANGE,ObjectKind.FILE,'=f',i) for i in range(200000)]
timed('add 200k unchanged', lambda: w._set_comparison_changes(changes+unchanged))
timed('remove 200k unchanged', lambda: w._set_comparison_changes(changes))
meta={f'd{i%30000}/f{i}.txt':(i%1000,'2026/11/20-12:00:00') for i in range(N) if i%3==0}
timed('destination metadata apply', lambda: v.set_destination_metadata(meta))
print('rows', v.row_count(), 'BENCH_DONE', flush=True)
