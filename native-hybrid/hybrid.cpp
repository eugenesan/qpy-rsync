// Production bridge for the hybrid app: Python owns rsync/parsing/validation,
// native Qt owns the view models and the volatile decision table.

#include <nanobind/nanobind.h>
#include <nanobind/stl/pair.h>
#include <nanobind/stl/unordered_map.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <QApplication>
#include <QColor>
#include <QIcon>
#include <QStyle>
#include <QCursor>
#include <QHBoxLayout>
#include <QMenu>
#include <QPainter>
#include <QFontMetrics>
#include <QHeaderView>
#include <QItemSelectionModel>
#include <QKeyEvent>
#include <QLabel>
#include <QPaintEvent>
#include <QMouseEvent>
#include <QScrollBar>
#include <QSizePolicy>
#include <QStyledItemDelegate>
#include <QSplitter>
#include <QTableView>
#include <QStyleOptionViewItem>
#include <QTreeView>
#include <QVBoxLayout>
#include <QWidget>

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

#include "model.hpp"

namespace nb = nanobind;

namespace {
class StatsWidget;
struct Session {
  DataStore store;
  QWidget* widget = nullptr;  // legacy combined widget
  QWidget* tables_widget = nullptr;
  QWidget* overview_widget = nullptr;
  QTreeView* overview_view = nullptr;
  StatsWidget* stats_widget = nullptr;
  std::vector<QString> action_colours;
  std::vector<QIcon> action_icons;
  int current_path_id = -1;
  int last_hidden_path_id = -1;
  bool sorting_link = false;
  TableModel* models[3] = {nullptr, nullptr, nullptr};
  OverviewModel* overview = nullptr;
  QTableView* views[3] = {nullptr, nullptr, nullptr};
};

Session& session() {
  static Session value;
  return value;
}

using SelectionHook = void (*)(int path_id);
using DecisionHook = void (*)(int path_id, int decision);
using ContextHook = void (*)(int pane, const char* path, int x, int y);

inline SelectionHook g_selection_hook = nullptr;
inline DecisionHook g_native_decision_hook = nullptr;
inline bool g_in_select = false;
inline bool g_in_sync = false;
inline bool g_profiling_enabled = false;

inline bool profiling_enabled() {
  if (g_profiling_enabled) return true;
  const char* value = std::getenv("QPY_RSYNC_PROFILE");
  return value != nullptr && value[0] != '\0';
}
inline nb::object g_selection_callback;
inline nb::object g_decision_callback;
inline nb::object g_context_callback;
inline nb::object g_header_context_callback;

void emit_selection(int path_id) {
  if (!g_in_select && g_selection_hook != nullptr) g_selection_hook(path_id);
}

void selection_hook(int path_id) {
  if (!g_selection_callback.is_valid()) return;
  nb::gil_scoped_acquire gil;
  try {
    g_selection_callback(path_id);
  } catch (...) {
  }
}

void native_decision_hook(int path_id, int decision) {
  if (!g_decision_callback.is_valid()) return;
  nb::gil_scoped_acquire gil;
  try {
    g_decision_callback(path_id, decision);
  } catch (...) {
  }
}

void context_hook(int pane, const char* path, int x, int y) {
  if (!g_context_callback.is_valid()) return;
  nb::gil_scoped_acquire gil;
  try {
    g_context_callback(pane, nb::str(path), x, y);
  } catch (...) {
  }
}

void header_context_hook(int pane, int x, int y) {
  if (!g_header_context_callback.is_valid()) return;
  nb::gil_scoped_acquire gil;
  try {
    g_header_context_callback(pane, x, y);
  } catch (...) {
  }
}

int first_visible_column(const Session& s, int pane);
void select_path_id_impl(Session& s, int path_id, bool center = false);

static std::vector<std::string> collect_expanded_paths(QTreeView* view) {
  std::vector<std::string> paths;
  if (view == nullptr || view->model() == nullptr) return paths;
  std::function<void(const QModelIndex&)> walk = [&](const QModelIndex& parent) {
    QAbstractItemModel* model = view->model();
    for (int row = 0; row < model->rowCount(parent); ++row) {
      QModelIndex index = model->index(row, 0, parent);
      if (!index.isValid()) continue;
      if (view->isExpanded(index)) {
        paths.push_back(model->data(index, Qt::UserRole).toString().toStdString());
        walk(index);
      }
    }
  };
  walk(QModelIndex());
  return paths;
}

void repaint_native_area(Session& s) {
  // A fold/expand resets the models and changes the viewport content. Under
  // X11+KWin the splitter sometimes kept stale native pixels below the view,
  // over the Python progress bar and journal. Updating the whole ancestor
  // chain forces the exposed sibling widgets to repaint their own backing
  // store instead of reusing the old native content.
  if (s.tables_widget != nullptr) {
    s.tables_widget->updateGeometry();
    for (QTableView* view : s.views) {
      if (view == nullptr) continue;
      if (view->viewport() != nullptr) view->viewport()->update();
      view->update();
    }
    QWidget* parent = s.tables_widget->parentWidget();
    if (parent != nullptr) {
      if (parent->layout() != nullptr) parent->layout()->activate();
      parent->update();
    }
    // The journal/progress live in sibling panes of the same window. Invalidate
    // the whole window so their backing store is repainted after the native
    // viewport changes height.
    if (QWidget* window = s.tables_widget->window()) window->update();
  }
  if (s.overview_widget != nullptr) {
    s.overview_widget->updateGeometry();
    if (s.overview_view != nullptr) s.overview_view->viewport()->update();
    s.overview_widget->update();
  }
}

void refresh_native_models(Session& s, bool expand_overview = false) {
  QWidget* focus = QApplication::focusWidget();
  int positions[3] = {0, 0, 0};
  int current_id = s.current_path_id;
  if (current_id < 0) {
    for (int i = 0; i < 3; ++i) {
      if (s.views[i] == nullptr) continue;
      const int row = s.views[i]->currentIndex().row();
      if (row >= 0 && row < static_cast<int>(s.store.visible.size())) {
        current_id = s.store.visible[row];
        break;
      }
    }
  }
  for (int i = 0; i < 3; ++i) {
    if (s.views[i] != nullptr && s.views[i]->verticalScrollBar() != nullptr) {
      positions[i] = s.views[i]->verticalScrollBar()->value();
    }
  }
  const std::vector<std::string> expanded_paths =
      collect_expanded_paths(s.overview_view);
  std::map<std::string, QModelIndex> path_index;
  QElapsedTimer phase;
  phase.start();
  for (TableModel* model : s.models) model->reset();
  if (profiling_enabled()) {
    std::fprintf(stderr, "[qpy-rsync native] model_reset ms=%lld\n",
                 static_cast<long long>(phase.elapsed()));
  }
  phase.restart();
  if (current_id >= 0 && current_id < static_cast<int>(s.store.row_of_id.size())) {
    if (s.store.row_of_id[current_id] < 0) {
      // Remember it: when undo brings it back, focus returns to this item.
      s.last_hidden_path_id = current_id;
      // The row was just hidden (for example by excluding it). Move to the
      // next visible item, or the previous one when it was the last.
      int nearest = -1;
      auto usable = [&](int candidate) {
        return candidate >= 0 &&
               candidate < static_cast<int>(s.store.paths.size()) &&
               s.store.paths[candidate] != DataStore::root_path();
      };
      auto is_dir = [&](int candidate) {
        return candidate < static_cast<int>(s.store.is_dir.size()) &&
               s.store.is_dir[candidate] != 0;
      };
      for (int candidate : s.store.visible) {
        if (!usable(candidate) || is_dir(candidate)) continue;
        if (candidate > current_id) { nearest = candidate; break; }
      }
      if (nearest < 0) {
        for (int index = static_cast<int>(s.store.visible.size()) - 1;
             index >= 0; --index) {
          const int candidate = s.store.visible[index];
          if (!usable(candidate) || is_dir(candidate)) continue;
          nearest = candidate;
          break;
        }
      }
      if (nearest < 0) {
        for (int candidate : s.store.visible) {
          if (usable(candidate)) { nearest = candidate; break; }
        }
      }
      current_id = nearest;
      s.current_path_id = current_id;
    }
    if (s.last_hidden_path_id >= 0 &&
        s.last_hidden_path_id < static_cast<int>(s.store.row_of_id.size()) &&
        s.store.row_of_id[s.last_hidden_path_id] >= 0) {
      current_id = s.last_hidden_path_id;
      s.last_hidden_path_id = -1;
      s.current_path_id = current_id;
    }
    if (current_id >= 0 && current_id < static_cast<int>(s.store.row_of_id.size()) &&
        s.store.row_of_id[current_id] >= 0) {
      select_path_id_impl(s, current_id);
    }
  }
  if (profiling_enabled()) {
    std::fprintf(stderr, "[qpy-rsync native] cursor_restore ms=%lld\n",
                 static_cast<long long>(phase.elapsed()));
  }
  // Restore the viewport last: a reset or scrollTo can move the bars, and
  // the user expects the list to stay at the same offset across undo.
  for (int i = 0; i < 3; ++i) {
    if (s.views[i] != nullptr && s.views[i]->verticalScrollBar() != nullptr) {
      s.views[i]->verticalScrollBar()->setValue(positions[i]);
    }
  }
  QWidget* list_focus = focus;
  if (list_focus == nullptr && s.views[0] != nullptr) list_focus = s.views[0];
  if (list_focus != nullptr) list_focus->setFocus();
  if (profiling_enabled()) {
    std::fprintf(stderr, "[qpy-rsync native] scroll_focus ms=%lld\n",
                 static_cast<long long>(phase.elapsed()));
  }
  if (expand_overview && s.overview != nullptr && s.overview_view != nullptr) {
    phase.restart();
    s.overview->build(s.store, true);
    if (profiling_enabled()) {
      std::fprintf(stderr, "[qpy-rsync native] overview_build ms=%lld\n",
                   static_cast<long long>(phase.elapsed()));
    }
    s.overview_view->expandToDepth(0);
    for (const std::string& path : expanded_paths) {
      const QModelIndex index = s.overview->index_for_path(path);
      if (index.isValid()) s.overview_view->expand(index);
    }
  }
  repaint_native_area(s);
}

int first_visible_column(const Session& s, int pane) {
  if (pane == 1) return 4;
  if (pane == 2) return 5;
  return 0;
}

void select_path_id_impl(Session& s, int path_id, bool center) {
  if (path_id < 0 || path_id >= static_cast<int>(s.store.row_of_id.size())) return;
  int row = s.store.row_of_id[path_id];
  s.current_path_id = path_id;
  g_in_select = true;
  for (int i = 0; i < 3; ++i) {
    QTableView* view = s.views[i];
    if (view == nullptr || view->model() == nullptr) continue;
    QModelIndex index = view->model()->index(row, first_visible_column(s, i));
    if (!index.isValid()) continue;
    view->selectionModel()->select(
        index, QItemSelectionModel::ClearAndSelect | QItemSelectionModel::Rows);
    view->setCurrentIndex(index);
    view->scrollTo(index, center ? QAbstractItemView::PositionAtCenter
                                 : QAbstractItemView::EnsureVisible);
  }
  g_in_select = false;
  emit_selection(path_id);
}

class StatsWidget : public QWidget {
 public:
  explicit StatsWidget(QWidget* parent = nullptr) : QWidget(parent) {}

  void setEntries(const std::vector<std::pair<QIcon, QString>>& entries) {
    entries_ = entries;
    updateGeometry();
    update();
  }

  QSize sizeHint() const override {
    int width = 4;
    for (const auto& entry : entries_) {
      width += 20 + fontMetrics().horizontalAdvance(entry.second) + 14;
    }
    return QSize(width, 24);
  }

 protected:
  void paintEvent(QPaintEvent*) override {
    QPainter painter(this);
    int x = 4;
    const int y = (height() - 16) / 2;
    for (const auto& entry : entries_) {
      if (!entry.first.isNull()) {
        entry.first.paint(&painter, QRect(x, y, 16, 16));
      }
      x += 20;
      painter.save();
      painter.setPen(palette().color(QPalette::Text));
      painter.drawText(x, height() / 2 + fontMetrics().ascent() / 2 - 1,
                       entry.second);
      x += fontMetrics().horizontalAdvance(entry.second) + 14;
      painter.restore();
    }
  }

 private:
  std::vector<std::pair<QIcon, QString>> entries_;
};

class OverviewDelegate : public QStyledItemDelegate {
 public:
  explicit OverviewDelegate(QObject* parent = nullptr)
      : QStyledItemDelegate(parent) {}

  void paint(QPainter* painter, const QStyleOptionViewItem& option,
             const QModelIndex& index) const override {
    if (index.column() != 1) {
      QStyledItemDelegate::paint(painter, option, index);
      return;
    }
    QStyleOptionViewItem blank(option);
    blank.text.clear();
    blank.icon = QIcon();
    blank.state &= ~(QStyle::State_HasFocus | QStyle::State_MouseOver);
    const QWidget* widget = blank.widget;
    QStyle* style = widget != nullptr ? widget->style() : QApplication::style();
    style->drawPrimitive(QStyle::PE_PanelItemViewItem, &blank, painter, widget);

    const QString text = index.data(Qt::DisplayRole).toString();
    const double share = index.data(Qt::UserRole + 20).toDouble();
    if (share > 0.0) {
      QColor color("#0891B2");
      color.setAlpha(120);
      const int width = static_cast<int>(option.rect.width() * qMin(1.0, share));
      painter->fillRect(option.rect.left(), option.rect.top(), width,
                        option.rect.height(), color);
    }
    painter->save();
    QColor color = (option.state & QStyle::State_Selected)
                       ? option.palette.color(QPalette::HighlightedText)
                       : option.palette.color(QPalette::Text);
    painter->setPen(color);
    painter->drawText(option.rect.adjusted(4, 0, -4, 0),
                      Qt::AlignLeft | Qt::AlignVCenter, text);
    painter->restore();
  }
};

void update_stats(Session& s);

class HybridKeyFilter : public QObject {
 public:
  explicit HybridKeyFilter(QObject* parent = nullptr) : QObject(parent) {}

  bool eventFilter(QObject* watched, QEvent* event) override {
    if (event->type() != QEvent::KeyPress) return false;
    auto* key = static_cast<QKeyEvent*>(event);
    Session& s = session();
    int pane = -1;
    for (int i = 0; i < 3; ++i) {
      if (s.views[i] == watched) pane = i;
    }
    if (pane < 0) return false;
    const int keyval = key->key();
    const DataStore& store = s.store;

    // Space is handled before the current-row fallback below: calling
    // setCurrentIndex() there clears a multi-row selection, which used to
    // leave only one item excluded.
    if (keyval == Qt::Key_Space) {
      std::vector<int> ids;
      QItemSelectionModel* selection = s.views[pane]->selectionModel();
      if (selection != nullptr) {
        for (const QModelIndex& selected : selection->selectedRows()) {
          const int selected_id = store.visible[selected.row()];
          if (selected_id < 0 ||
              selected_id >= static_cast<int>(store.paths.size()) ||
              store.paths[selected_id] == DataStore::root_path() ||
              store.decisions[selected_id] == DeleteRequest) {
            continue;
          }
          ids.push_back(selected_id);
        }
      }
      if (ids.empty()) {
        const int current = s.views[pane]->currentIndex().row();
        if (current >= 0 && current < static_cast<int>(store.visible.size())) {
          const int candidate = store.visible[current];
          if (candidate >= 0 &&
              candidate < static_cast<int>(store.paths.size()) &&
              store.paths[candidate] != DataStore::root_path()) {
            ids.push_back(candidate);
          }
        }
      }
      if (ids.empty()) return true;
      const bool exclude = store.decisions[ids.front()] != Exclude;
      const int decision = exclude ? Exclude : Inherit;
      for (int selected_id : ids) {
        s.store.set_decision_id(selected_id, decision, true);
        if (g_native_decision_hook != nullptr) {
          g_native_decision_hook(selected_id, decision);
        }
      }
      s.store.rebuild_visible();
      refresh_native_models(s);
      update_stats(s);
      return true;
    }

    int row = s.views[pane]->currentIndex().row();
    if (row < 0 || row >= static_cast<int>(store.visible.size())) {
      if (store.visible.empty()) return false;
      row = 0;
      QModelIndex first = s.views[pane]->model()->index(
          0, first_visible_column(s, pane));
      if (first.isValid()) s.views[pane]->setCurrentIndex(first);
    }
    const int id = store.visible[row];

    if (keyval == Qt::Key_Home || keyval == Qt::Key_End) {
      const bool last = keyval == Qt::Key_End;
      for (int r = last ? static_cast<int>(store.visible.size()) - 1 : 0;
           last ? r >= 0 : r < static_cast<int>(store.visible.size());
           last ? --r : ++r) {
        const int candidate = store.visible[r];
        if (!(candidate < static_cast<int>(store.is_dir.size()) &&
              store.is_dir[candidate])) {
          select_path_id_impl(s, candidate);
          return true;
        }
      }
      return true;
    }
    if (key->modifiers() & Qt::ControlModifier) {
      if (keyval == Qt::Key_Up) {
        int parent = id < static_cast<int>(store.parents.size())
                         ? store.parents[id] : -1;
        while (parent >= 0 && parent < static_cast<int>(store.row_of_id.size()) &&
               store.row_of_id[parent] < 0) {
          parent = parent < static_cast<int>(store.parents.size())
                       ? store.parents[parent] : -1;
        }
        if (parent >= 0) select_path_id_impl(s, parent);
        return true;
      }
      if (keyval == Qt::Key_Down) {
        for (int r = row + 1; r < static_cast<int>(store.visible.size()); ++r) {
          const int candidate = store.visible[r];
          int parent = candidate < static_cast<int>(store.parents.size())
                           ? store.parents[candidate] : -1;
          while (parent >= 0 && parent != id) {
            parent = parent < static_cast<int>(store.parents.size())
                         ? store.parents[parent] : -1;
          }
          if (parent == id) {
            select_path_id_impl(s, candidate);
            return true;
          }
        }
        return true;
      }
      return false;
    }
    if (keyval == Qt::Key_Left || keyval == Qt::Key_Right) {
      const bool is_dir = id < static_cast<int>(store.is_dir.size()) &&
                          store.is_dir[id];
      const bool root = store.paths[id] == DataStore::root_path();
      if (is_dir && !root) {
        const bool collapsed = id < static_cast<int>(store.collapsed.size()) &&
                               store.collapsed[id];
        if (keyval == Qt::Key_Left) {
          if (!collapsed) {
            toggle_collapse(s, id);
          } else {
            const int parent = store.parents[id];
            if (parent >= 0) select_path_id_impl(s, parent);
          }
          return true;
        }
        if (collapsed) {
          toggle_collapse(s, id);
          return true;
        }
        if (row + 1 < static_cast<int>(store.visible.size())) {
          const int child = store.visible[row + 1];
          const int parent = child < static_cast<int>(store.parents.size())
                                 ? store.parents[child] : -1;
          if (parent == id) {
            select_path_id_impl(s, child);
          }
        }
        return true;
      }
      if (keyval == Qt::Key_Left) {
        const int parent = id < static_cast<int>(store.parents.size())
                               ? store.parents[id] : -1;
        if (parent >= 0) select_path_id_impl(s, parent);
      }
      return true;
    }
    return false;
  }

 private:
  static void toggle_collapse(Session& s, int id) {
    s.store.collapsed[id] = s.store.collapsed[id] ? 0 : 1;
    s.store.rebuild_visible();
    refresh_native_models(s);
  }
};

class HybridDelegate : public QStyledItemDelegate {
 public:
  HybridDelegate(Session* session, int pane, QObject* parent = nullptr)
      : QStyledItemDelegate(parent), session_(session), pane_(pane) {}

  bool editorEvent(QEvent* event, QAbstractItemModel*,
                   const QStyleOptionViewItem& option,
                   const QModelIndex& index) override {
    if (event->type() != QEvent::MouseButtonPress) return false;
    auto* mouse = static_cast<QMouseEvent*>(event);
    if (mouse->button() != Qt::LeftButton) return false;
    Session& s = *session_;
    const DataStore& store = s.store;
    const int row = index.row();
    if (row < 0 || row >= static_cast<int>(store.visible.size())) return false;
    const int id = store.visible[row];
    if (pane_ == 1 && index.column() == 4) {
      const int group_width = 16 + 8 + 16;
      const int start = option.rect.left() + qMax(0, (option.rect.width() - group_width) / 2);
      QRect indicator(start, option.rect.center().y() - 8, 16, 16);
      if (indicator.contains(mouse->pos())) {
        // Apply the click to every selected row, not just the clicked one.
        std::vector<int> ids;
        QItemSelectionModel* selection = s.views[1]->selectionModel();
        if (selection != nullptr) {
          for (const QModelIndex& selected : selection->selectedRows()) {
            const int selected_id = store.visible[selected.row()];
            if (selected_id < 0 ||
                selected_id >= static_cast<int>(store.paths.size()) ||
                store.paths[selected_id] == DataStore::root_path() ||
                store.decisions[selected_id] == DeleteRequest) {
              continue;
            }
            ids.push_back(selected_id);
          }
        }
        if (ids.empty()) ids.push_back(id);
        const int decision = store.decisions[ids.front()] == Exclude
                                 ? Inherit
                                 : Exclude;
        for (int selected_id : ids) {
          s.store.set_decision_id(selected_id, decision, true);
          if (g_native_decision_hook != nullptr) {
            g_native_decision_hook(selected_id, decision);
          }
        }
        // Folder ids live beyond the change list, so the Python mirror may
        // not call back. Always rebuild our own visible rows here.
        s.store.rebuild_visible();
        refresh_native_models(s);
        return true;
      }
    }
    if (!(id < static_cast<int>(store.is_dir.size()) && store.is_dir[id])) {
      return false;
    }
    const int depth = id < static_cast<int>(store.depth.size()) ? store.depth[id] : 0;
    QRect hit(option.rect.left() + 4 + depth * 14 - 1,
              option.rect.center().y() - 5, 10, 10);
    if (!hit.contains(mouse->pos())) return false;
    s.store.collapsed[id] = s.store.collapsed[id] ? 0 : 1;
    s.store.rebuild_visible();
    refresh_native_models(s);
    return true;
  }

  void paint(QPainter* painter, const QStyleOptionViewItem& option,
             const QModelIndex& index) const override {
    Session& s = *session_;
    const DataStore& store = s.store;
    const int row = index.row();
    const int col = index.column();
    if (row < 0 || row >= static_cast<int>(store.visible.size())) {
      QStyledItemDelegate::paint(painter, option, index);
      return;
    }
    const int id = store.visible[row];
    if (pane_ == 1) {
      paint_check(painter, option, index, s, store, id);
      return;
    }
    const int action = id < static_cast<int>(store.actions.size())
                           ? store.actions[id] : NoChange;
    const bool source_present = action != DestOnly && action != Delete;
    const bool dest_present = action != Create;
    const bool dir_row = id < static_cast<int>(store.is_dir.size()) && store.is_dir[id];
    if (!dir_row && ((pane_ == 0 && !source_present) ||
                     (pane_ == 2 && !dest_present))) {
      QStyleOptionViewItem blank(option);
      initStyleOption(&blank, index);
      paint_background(painter, option, false);
      return;
    }

    const bool name_col = (col == 0 || col == 5);
    QStyleOptionViewItem opt(option);
    initStyleOption(&opt, index);
    const bool selected = opt.state & QStyle::State_Selected;
    const bool striped = !selected && row < static_cast<int>(store.stripe.size()) &&
                         store.stripe[row] != 0;
    // QStyledItemDelegate::paint re-reads the text (and its brush) from the
    // model, which loses the action colour on some styles. Paint the row
    // background and every cell's text ourselves.
    paint_background(painter, option, striped);
    if (!name_col) {
      QColor color = text_color(s, store, id, selected);
      if (!color.isValid()) color = opt.palette.color(QPalette::Text);
      const int alignment = Qt::AlignLeft | Qt::AlignVCenter;
      painter->save();
      painter->setPen(color);
      painter->drawText(opt.rect.adjusted(2, 0, -4, 0), alignment,
                        index.data(Qt::DisplayRole).toString());
      painter->restore();
      return;
    }

    // Directory hierarchy: indentation, fold marker, icon and name.
    const bool is_dir = id < static_cast<int>(store.is_dir.size()) && store.is_dir[id];
    const int depth = id < static_cast<int>(store.depth.size()) ? store.depth[id] : 0;
    QColor color = text_color(s, store, id, selected);
    if (!color.isValid()) color = opt.palette.color(QPalette::Text);
    int x = opt.rect.left() + 4 + depth * 14;
    const int mid = opt.rect.center().y();
    const int baseline = opt.rect.top() + opt.rect.height() / 2 +
                         opt.fontMetrics.ascent() / 2 - 1;
    painter->save();
    const bool has_children = is_dir &&
        id < static_cast<int>(store.dir_has_children.size()) &&
        store.dir_has_children[id];
    const bool root_row = store.paths[id] == DataStore::root_path();
    // Reserve the fold-marker gutter on every row so empty folders stay
    // aligned with folders that have children, and files line up with them.
    if (root_row) {
      const QIcon& icon = store.root_icon;
      if (!icon.isNull()) icon.paint(painter, QRect(x, mid - 8, 16, 16));
      else draw_folder_icon(painter, QRect(x, mid - 8, 16, 14));
      x += 20;
    } else if (is_dir) {
      const bool expanded = !(id < static_cast<int>(store.collapsed.size()) &&
                              store.collapsed[id]);
      if (has_children) {
        painter->setPen(Qt::NoPen);
        painter->setBrush(color);
        QRect chev(x, mid - 4, 8, 8);
        if (expanded) {
          QPoint pts[3] = {{chev.left(), chev.top()},
                           {chev.right(), chev.top()},
                           {chev.center().x(), chev.bottom()}};
          painter->drawPolygon(pts, 3);
        } else {
          QPoint pts[3] = {{chev.left(), chev.top()},
                           {chev.right(), chev.center().y()},
                           {chev.left(), chev.bottom()}};
          painter->drawPolygon(pts, 3);
        }
      }
      const int icon_x = x + 14;
      if (!store.folder_icon.isNull()) {
        store.folder_icon.paint(painter, QRect(icon_x, mid - 8, 16, 16));
      } else {
        draw_folder_icon(painter, QRect(icon_x, mid - 8, 16, 14));
      }
      x = icon_x + 20;
    } else {
      const int icon_x = x + 14;
      painter->setPen(QPen(QColor("#D0D7DE"), 1));
      painter->drawLine(x + 10, opt.rect.top(), x + 10, opt.rect.bottom());
      std::string suffix;
      const std::string& path = store.paths[id];
      const std::size_t dot = path.rfind('.');
      const std::size_t slash = path.rfind('/');
      if (dot != std::string::npos && (slash == std::string::npos || dot > slash)) {
        suffix = path.substr(dot + 1);
      }
      auto found = store.file_icons.find(suffix);
      if (found == store.file_icons.end()) found = store.file_icons.find("");
      if (found != store.file_icons.end() && !found->second.isNull()) {
        found->second.paint(painter, QRect(icon_x, mid - 8, 16, 16));
      }
      else draw_file_icon(painter, QRect(icon_x + 1, mid - 9, 14, 16), color);
      x = icon_x + 20;
    }
    painter->setPen(color);
    const int available = opt.rect.right() - x - 4;
    const QString text = index.data(Qt::DisplayRole).toString();
    painter->drawText(x, baseline,
                      opt.fontMetrics.elidedText(text, Qt::ElideRight, available));
    painter->restore();
  }

 private:
  void paint_background(QPainter* painter, const QStyleOptionViewItem& option,
                        bool striped) const {
    QStyleOptionViewItem blank(option);
    blank.text.clear();
    blank.icon = QIcon();
    blank.state &= ~(QStyle::State_HasFocus | QStyle::State_MouseOver);
    if (striped) {
      // Python paints a faint black overlay (alpha 22). The palette's
      // alternate base was visibly lighter, so use the midpoint.
      painter->fillRect(blank.rect, QColor(0, 0, 0, 14));
    }
    const QWidget* widget = blank.widget;
    QStyle* style = widget != nullptr ? widget->style() : QApplication::style();
    style->drawPrimitive(QStyle::PE_PanelItemViewItem, &blank, painter, widget);
  }

  QColor text_color(const Session& s, const DataStore& store, int id,
                    bool selected) const {
    if (selected) return {};
    const int action = id < static_cast<int>(store.actions.size())
                           ? store.actions[id] : NoChange;
    if (action >= 0 && action < static_cast<int>(s.action_colours.size())) {
      const QString hex = s.action_colours[action];
      if (!hex.isEmpty()) return QColor(hex);
    }
    if (id < static_cast<int>(store.decisions.size()) &&
        store.decisions[id] == Exclude) {
      return QColor("#9CA3AF");
    }
    return {};
  }

  void draw_folder_icon(QPainter* painter, const QRect& r) const {
    painter->save();
    painter->setPen(QPen(QColor("#B8860B"), 1));
    painter->setBrush(QColor("#F4C542"));
    painter->drawRect(QRect(r.left(), r.top() + 3, r.width(), r.height() - 3));
    painter->drawRect(QRect(r.left(), r.top(), r.width() / 2, 4));
    painter->restore();
  }

  void draw_file_icon(QPainter* painter, const QRect& r,
                      const QColor& tint) const {
    painter->save();
    QColor fill = tint.isValid() ? tint : QColor("#EAB308");
    fill.setAlpha(48);
    painter->setBrush(fill);
    painter->setPen(QPen(tint.isValid() ? tint : QColor("#B8860B"), 1));
    painter->drawRect(r);
    painter->drawLine(r.right() - 4, r.top(), r.right() - 4, r.top() + 4);
    painter->drawLine(r.right() - 4, r.top() + 4, r.right(), r.top() + 4);
    painter->restore();
  }

  void paint_check(QPainter* painter, const QStyleOptionViewItem& option,
                   const QModelIndex& index, Session& s,
                   const DataStore& store, int id) const {
    QStyleOptionViewItem opt(option);
    initStyleOption(&opt, index);
    paint_background(painter, option, false);
    const bool delete_request =
        id < static_cast<int>(store.decisions.size()) &&
        store.decisions[id] == DeleteRequest;
    const bool checked = index.data(Qt::CheckStateRole).toInt() == Qt::Checked;
    // Paint the same rounded, accent-coloured checkbox the toolbar QCheckBox
    // uses under Breeze; the item-view indicator primitive draws a dash here.
    // Center the checkbox + action icon group in the Decisions pane.
    const int group_width = delete_request ? 16 : 16 + 8 + 16;
    const int start = opt.rect.left() + qMax(0, (opt.rect.width() - group_width) / 2);
    QRect box(start, opt.rect.center().y() - 8, 16, 16);
    if (!delete_request) {
      painter->save();
      painter->setRenderHint(QPainter::Antialiasing);
      painter->setPen(Qt::NoPen);
      painter->setBrush(opt.palette.color(QPalette::Highlight));
      painter->drawRoundedRect(box, 4, 4);
      if (checked) {
        painter->setRenderHint(QPainter::Antialiasing, true);
        painter->setPen(QPen(opt.palette.color(QPalette::HighlightedText), 2,
                             Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin));
        painter->drawLine(box.left() + 4, box.center().y(), box.left() + 7,
                          box.bottom() - 4);
        painter->drawLine(box.left() + 7, box.bottom() - 4, box.right() - 4,
                          box.top() + 4);
      }
      painter->restore();
    }
    int action = store.actions[id];
    if (delete_request) {
      action = Delete;
    }
    if (action >= 0 && action < static_cast<int>(s.action_icons.size()) &&
        !s.action_icons[action].isNull()) {
      // Reuse the exact QIcon the Python view generates, so the toolbar,
      // Decisions column and overview statistics always agree.
      const int y = opt.rect.center().y() - 8;
      s.action_icons[action].paint(
          painter, QRect(delete_request ? start : start + 24, y, 16, 16));
    }
  }

  Session* session_;
  int pane_;
};

void update_stats(Session& s);

static int logical_sort_column(int section) {
  switch (section) {
    case 0: case 5: return 0;   // name
    case 1: case 6: return 1;   // items
    case 2: case 7: return 2;   // size
    case 3: case 8: return 3;   // modified
    case 4: return 4;           // decision
    case 9: case 10: return 9;  // size in bytes
    default: return 0;
  }
}

static int sort_section(int logical, int pane) {
  if (pane == 1) return logical == 4 ? 4 : -1;
  if (logical == 4) return -1;
  if (pane == 0) {
    return logical == 9 ? 9 : logical;
  }
  switch (logical) {
    case 0: return 5;
    case 1: return 6;
    case 2: return 7;
    case 3: return 8;
    case 9: return 10;
    default: return 5;
  }
}

QWidget* ensure_tables_widget(Session& s) {
  if (s.tables_widget == nullptr) {
    s.tables_widget = new QWidget();
    auto* outer = new QVBoxLayout(s.tables_widget);
    outer->setContentsMargins(0, 0, 0, 0);
    auto* splitter = new QSplitter(Qt::Horizontal, s.tables_widget);
    splitter->setChildrenCollapsible(false);
    outer->addWidget(splitter);
    QTableView* views[3];
    for (int i = 0; i < 3; ++i) {
      views[i] = new QTableView(s.tables_widget);
      views[i]->verticalHeader()->setDefaultSectionSize(22);
      views[i]->verticalHeader()->hide();
      views[i]->horizontalHeader()->setStretchLastSection(true);
      // Only the destination pane shows a scrollbar; the other two follow it.
      views[i]->setVerticalScrollBarPolicy(
          i == 2 ? Qt::ScrollBarAlwaysOn : Qt::ScrollBarAlwaysOff);
      views[i]->setSelectionBehavior(QAbstractItemView::SelectRows);
      views[i]->horizontalHeader()->setHighlightSections(false);
      // Handle sorting ourselves in the linked slot below; QTableView's
      // built-in handler would sort the model a second time.
      views[i]->horizontalHeader()->setSectionsClickable(true);
      views[i]->horizontalHeader()->setSortIndicatorShown(true);
      views[i]->horizontalHeader()->setSortIndicator(0, Qt::AscendingOrder);
      QObject::connect(
          views[i]->horizontalHeader(), &QHeaderView::sortIndicatorChanged,
          [](int section, Qt::SortOrder order) {
            Session& current = session();
            if (current.sorting_link) return;
            const int logical = logical_sort_column(section);
            current.sorting_link = true;
            current.store.sort_column = logical;
            current.store.sort_desc = order == Qt::DescendingOrder;
            current.store.rebuild_visible();
            for (int pane = 0; pane < 3; ++pane) {
              QHeaderView* header = current.views[pane]->horizontalHeader();
              const bool blocked = header->blockSignals(true);
              header->setSortIndicator(sort_section(logical, pane), order);
              header->blockSignals(blocked);
            }
            refresh_native_models(current);
            update_stats(current);
            current.sorting_link = false;
          });
      splitter->addWidget(views[i]);
    }
    for (int i = 0; i < 3; ++i) s.views[i] = views[i];
    s.models[0] = new TableModel(&s.store, 0, s.tables_widget);
    s.models[1] = new TableModel(&s.store, 1, s.tables_widget);
    s.models[2] = new TableModel(&s.store, 2, s.tables_widget);
    views[0]->setModel(s.models[0]);
    views[1]->setModel(s.models[1]);
    views[2]->setModel(s.models[2]);
    for (int pane = 0; pane < 3; ++pane) {
      QHeaderView* header = views[pane]->horizontalHeader();
      const bool blocked = header->blockSignals(true);
      header->setSortIndicator(sort_section(0, pane), Qt::AscendingOrder);
      header->blockSignals(blocked);
    }
    for (int hidden : {3, 4, 5, 6, 7, 8, 9, 10}) views[0]->setColumnHidden(hidden, true);
    for (int column = 0; column < 11; ++column) {
      views[1]->setColumnHidden(column, column != 4);
    }
    for (int hidden : {0, 1, 2, 3, 4, 8, 9, 10}) views[2]->setColumnHidden(hidden, true);
    views[0]->horizontalHeader()->setStretchLastSection(false);
    views[0]->horizontalHeader()->setSectionResizeMode(0, QHeaderView::Stretch);
    views[0]->horizontalHeader()->setSectionResizeMode(1, QHeaderView::Fixed);
    views[0]->horizontalHeader()->resizeSection(1, 60);
    views[0]->horizontalHeader()->setSectionResizeMode(2, QHeaderView::Fixed);
    views[0]->horizontalHeader()->resizeSection(2, 96);
    views[2]->horizontalHeader()->setStretchLastSection(false);
    views[2]->horizontalHeader()->setSectionResizeMode(5, QHeaderView::Stretch);
    views[2]->horizontalHeader()->setSectionResizeMode(6, QHeaderView::Fixed);
    views[2]->horizontalHeader()->resizeSection(6, 60);
    views[2]->horizontalHeader()->setSectionResizeMode(7, QHeaderView::Fixed);
    views[2]->horizontalHeader()->resizeSection(7, 96);
    views[1]->horizontalHeader()->setSectionResizeMode(4, QHeaderView::Fixed);
    views[1]->horizontalHeader()->resizeSection(4, 88);
    views[1]->setStyleSheet(
        "QTableView { border-left: 1px solid palette(mid);"
        " border-right: 1px solid palette(mid); }");
    for (QTableView* view : views) {
      view->horizontalHeader()->setFixedHeight(
          qMax(16, view->fontMetrics().height() + 2));
      view->setAlternatingRowColors(false);
    }
    for (int i = 0; i < 3; ++i) {
      views[i]->installEventFilter(new HybridKeyFilter(views[i]));
      views[i]->setItemDelegate(new HybridDelegate(&s, i, s.tables_widget));
      views[i]->setContextMenuPolicy(Qt::CustomContextMenu);
      if (i != 1) {
        QHeaderView* header = views[i]->horizontalHeader();
        header->setContextMenuPolicy(Qt::CustomContextMenu);
        QObject::connect(
            header, &QHeaderView::customContextMenuRequested,
            [i](const QPoint& pos) {
              Session& current = session();
              QPoint global = current.views[i]->horizontalHeader()->mapToGlobal(pos);
              header_context_hook(i, global.x(), global.y());
            });
      }
      QObject::connect(
          views[i], &QTableView::customContextMenuRequested,
          [i](const QPoint& pos) {
            Session& current = session();
            if (current.views[i] == nullptr) return;
            QModelIndex index = current.views[i]->indexAt(pos);
            if (!index.isValid()) return;
            int row = index.row();
            if (row < 0 || row >= static_cast<int>(current.store.visible.size())) return;
            int id = current.store.visible[row];
            std::string path = current.store.paths[id];
            QPoint global = current.views[i]->viewport()->mapToGlobal(pos);
            context_hook(i, path.c_str(), global.x(), global.y());
          });
    }
    for (int i = 0; i < 3; ++i) {
      for (int j = i + 1; j < 3; ++j) {
        QObject::connect(views[i]->verticalScrollBar(), &QScrollBar::valueChanged,
                         views[j]->verticalScrollBar(), &QScrollBar::setValue);
        QObject::connect(views[j]->verticalScrollBar(), &QScrollBar::valueChanged,
                         views[i]->verticalScrollBar(), &QScrollBar::setValue);
      }
    }
    for (QTableView* view : views) {
      QObject::connect(
          view->selectionModel(), &QItemSelectionModel::selectionChanged,
          [](const QItemSelection& selected, const QItemSelection&) {
            if (selected.isEmpty()) return;
            QModelIndex index = selected.first().indexes().first();
            Session& current = session();
            int row = index.row();
            if (row >= 0 && row < static_cast<int>(current.store.visible.size())) {
              current.current_path_id = current.store.visible[row];
              emit_selection(current.current_path_id);
            }
          });
    }
    // Keep the focus row and selection aligned across the three panes.
    for (int i = 0; i < 3; ++i) {
      for (int j = 0; j < 3; ++j) {
        if (i == j) continue;
        QObject::connect(
            views[i]->selectionModel(), &QItemSelectionModel::currentChanged,
            [j](const QModelIndex& current, const QModelIndex&) {
              if (g_in_select || g_in_sync) return;
              Session& s = session();
              if (current.isValid() && current.row() >= 0 &&
                  current.row() < static_cast<int>(s.store.visible.size())) {
                s.current_path_id = s.store.visible[current.row()];
              }
              if (!current.isValid()) return;
              QTableView* target = s.views[j];
              if (target == nullptr || target->model() == nullptr) return;
              QModelIndex index = target->model()->index(
                  current.row(), first_visible_column(s, j));
              if (!index.isValid()) return;
              g_in_sync = true;
              target->setCurrentIndex(index);
              target->selectionModel()->select(
                  index, QItemSelectionModel::ClearAndSelect |
                             QItemSelectionModel::Rows);
              g_in_sync = false;
            });
      }
    }
    splitter->setStretchFactor(0, 1);
    splitter->setStretchFactor(1, 0);
    splitter->setStretchFactor(2, 1);
    splitter->setSizes({900, 80, 900});
    QSizePolicy policy = views[1]->sizePolicy();
    policy.setHorizontalPolicy(QSizePolicy::Fixed);
    views[1]->setSizePolicy(policy);
    views[1]->setFixedWidth(92);
    s.tables_widget->setMinimumWidth(700);
  }
  return s.tables_widget;
}

QWidget* ensure_overview_widget(Session& s) {
  if (s.overview_widget == nullptr) {
    s.overview_widget = new QWidget();
    auto* layout = new QVBoxLayout(s.overview_widget);
    layout->setContentsMargins(0, 0, 0, 0);
    s.stats_widget = new StatsWidget(s.overview_widget);
    s.overview_view = new QTreeView(s.overview_widget);
    s.overview_view->setUniformRowHeights(true);
    s.overview_view->setAlternatingRowColors(true);
    s.overview_view->setRootIsDecorated(true);
    s.overview_view->header()->setHighlightSections(false);
    s.overview_view->header()->setDefaultAlignment(Qt::AlignHCenter);
    s.overview_view->header()->setFixedHeight(
        qMax(16, s.overview_view->fontMetrics().height() + 2));
    s.overview = new OverviewModel(s.overview_widget);
    s.overview_view->setModel(s.overview);
    s.overview_view->setItemDelegate(new OverviewDelegate(s.overview_widget));
    s.overview_view->header()->setStretchLastSection(false);
    s.overview_view->header()->setSectionResizeMode(0, QHeaderView::Stretch);
    s.overview_view->header()->setSectionResizeMode(1, QHeaderView::Fixed);
    s.overview_view->header()->resizeSection(1, 56);
    s.overview_view->header()->setSectionResizeMode(2, QHeaderView::Fixed);
    s.overview_view->header()->resizeSection(2, 64);
    s.overview_view->header()->setSectionResizeMode(3, QHeaderView::Fixed);
    s.overview_view->header()->resizeSection(3, 84);
    s.overview_view->expandToDepth(0);
    layout->addWidget(s.overview_view);
    layout->addWidget(s.stats_widget);
    QObject::connect(
        s.overview_view, &QTreeView::activated,
        [](const QModelIndex& index) {
          Session& current = session();
          QString path = current.overview->data(index, Qt::UserRole).toString();
          auto it = current.store.path_to_id.find(path.toStdString());
          if (it != current.store.path_to_id.end()) {
            select_path_id_impl(current, it->second, true);
            // Put keyboard focus back on the lists so arrows and shortcuts
            // act on the jumped-to row immediately.
            if (current.views[0] != nullptr) current.views[0]->setFocus();
          }
        });
  }
  return s.overview_widget;
}

void update_stats(Session& s) {
  if (s.stats_widget == nullptr) return;
  long long count = 0, size = 0, creates = 0, updates = 0, metadata = 0,
              deletes = 0, kept = 0, deleted_size = 0;
  for (int id : s.store.visible) {
    if (id < 0 || id >= static_cast<int>(s.store.is_dir.size())) continue;
    if (s.store.is_dir[id]) continue;
    int action = id < static_cast<int>(s.store.actions.size())
                     ? s.store.actions[id] : NoChange;
    if (id < static_cast<int>(s.store.decisions.size()) &&
        s.store.decisions[id] == Exclude) {
      continue;
    }
    ++count;
    size += id < static_cast<int>(s.store.sizes.size()) ? s.store.sizes[id] : 0;
    if (id < static_cast<int>(s.store.decisions.size()) &&
        s.store.decisions[id] == DeleteRequest) {
      action = Delete;
    }
    if (action == Create) ++creates;
    else if (action == Update) ++updates;
    else if (action == Metadata) ++metadata;
    else if (action == Delete) {
      ++deletes;
      deleted_size += id < static_cast<int>(s.store.dest_sizes.size())
                          ? s.store.dest_sizes[id] : 0;
    } else if (action == DestOnly) ++kept;
  }
  auto icon_for = [&](int action) -> QIcon {
    return action >= 0 && action < static_cast<int>(s.action_icons.size())
               ? s.action_icons[action] : QIcon();
  };
  std::vector<std::pair<QIcon, QString>> entries;
  entries.emplace_back(QIcon(), QString("%1 item(s), %2")
                                    .arg(count).arg(qpy_format_size(size)));
  entries.emplace_back(icon_for(Create), QString::number(creates));
  entries.emplace_back(icon_for(Update), QString::number(updates));
  entries.emplace_back(icon_for(Metadata), QString::number(metadata));
  entries.emplace_back(icon_for(Delete),
                       QString("%1 (%2)").arg(deletes).arg(
                           qpy_format_size(deleted_size)));
  entries.emplace_back(icon_for(DestOnly), QString::number(kept));
  s.stats_widget->setEntries(entries);
}

}  // namespace

NB_MODULE(native_hybrid, m) {
  m.doc() = "Native Qt view layer for qpy-rsync";

  m.def("load", [](const std::vector<std::string>& paths,
                   const std::vector<int>& actions,
                   const std::vector<int>& kinds,
                   const std::vector<long long>& sizes,
                   const std::vector<int>& decisions,
                   const std::vector<std::string>& times) {
    session().store.load_direct(paths, actions, kinds, sizes, decisions, times);
  });

  m.def("truncate", [](int count) {
    Session& s = session();
    s.store.truncate(count);
  });

  m.def("append", [](const std::vector<std::string>& paths,
                     const std::vector<int>& actions,
                     const std::vector<int>& kinds,
                     const std::vector<long long>& sizes,
                     const std::vector<int>& decisions,
                     const std::vector<std::string>& times) {
    session().store.append_direct(paths, actions, kinds, sizes, decisions, times);
  });

  m.def("set_selection_callback", [](nb::object callback) {
    g_selection_callback = callback;
    g_selection_hook = &selection_hook;
  });

  m.def("set_decision_callback", [](nb::object callback) {
    g_decision_callback = callback;
    g_native_decision_hook = &native_decision_hook;
    g_decision_hook = &native_decision_hook;
  });

  m.def("shutdown", []() {
    g_selection_hook = nullptr;
    g_native_decision_hook = nullptr;
    g_decision_hook = nullptr;
    g_selection_callback = nb::object();
    g_decision_callback = nb::object();
    g_context_callback = nb::object();
    g_header_context_callback = nb::object();
    Session& session_ref = session();
    for (int i = 0; i < 3; ++i) {
      session_ref.views[i] = nullptr;
      session_ref.models[i] = nullptr;
    }
    session_ref.overview_view = nullptr;
    session_ref.overview = nullptr;
    session_ref.stats_widget = nullptr;
    session_ref.tables_widget = nullptr;
    session_ref.overview_widget = nullptr;
  });

  m.def("debug_row_of_id", [](int path_id) {
    Session& s = session();
    return path_id >= 0 && path_id < static_cast<int>(s.store.row_of_id.size())
               ? s.store.row_of_id[path_id] : -2;
  });

  m.def("debug_selected_row", []() {
    Session& s = session();
    if (s.views[0] == nullptr || s.views[0]->selectionModel() == nullptr) return -2;
    QModelIndexList rows = s.views[0]->selectionModel()->selectedRows();
    return rows.isEmpty() ? -1 : rows.first().row();
  });

  m.def("select_path_id", [](int path_id) { select_path_id_impl(session(), path_id); });

  m.def("select_path", [](const std::string& path) {
    Session& s = session();
    auto it = s.store.path_to_id.find(path);
    if (it == s.store.path_to_id.end()) return;
    const int id = it->second;
    bool changed = false;
    int parent = id < static_cast<int>(s.store.parents.size())
                     ? s.store.parents[id] : -1;
    while (parent >= 0) {
      if (parent < static_cast<int>(s.store.collapsed.size()) &&
          s.store.collapsed[parent]) {
        s.store.collapsed[parent] = 0;
        changed = true;
      }
      parent = parent < static_cast<int>(s.store.parents.size())
                   ? s.store.parents[parent] : -1;
    }
    if (changed) {
      s.store.rebuild_visible();
      refresh_native_models(s);
    }
    select_path_id_impl(s, id);
  });

  m.def("apply_destination_metadata",
        [](const std::unordered_map<std::string, std::pair<long long, std::string>>& metadata,
           bool merge) {
          Session& s = session();
          s.store.apply_destination_metadata(metadata, merge);
          refresh_native_models(s);
        });

  m.def("focus_lists", []() {
    Session& s = session();
    if (s.views[0] != nullptr) s.views[0]->setFocus();
  });

  m.def("overview_folder_count", []() {
    Session& s = session();
    if (s.overview == nullptr) return 0;
    QModelIndex root = s.overview->index(0, 0);
    if (!root.isValid()) return 0;
    QModelIndex all = s.overview->index(0, 0, root);
    return all.isValid() ? s.overview->rowCount(all) : 0;
  });

  m.def("row_count", []() {
    return static_cast<int>(session().store.visible.size());
  });

  m.def("create_tables_widget", []() {
    return reinterpret_cast<std::uintptr_t>(ensure_tables_widget(session()));
  });

  m.def("create_overview_widget", []() {
    return reinterpret_cast<std::uintptr_t>(ensure_overview_widget(session()));
  });

  m.def("update_stats", []() { update_stats(session()); });

  m.def("create_widget", []() {
    Session& s = session();
    if (s.widget == nullptr) {
      QWidget* tables = ensure_tables_widget(s);
      QWidget* overview = ensure_overview_widget(s);
      s.widget = new QWidget();
      auto* layout = new QHBoxLayout(s.widget);
      layout->addWidget(tables);
      layout->addWidget(overview);
      s.widget->setMinimumSize(1000, 500);
      s.widget->resize(1600, 800);
    }
    return reinterpret_cast<std::uintptr_t>(s.widget);
  });

  m.def("set_context_callback", [](nb::object callback) {
    g_context_callback = callback;
  });

  m.def("set_header_context_callback", [](nb::object callback) {
    g_header_context_callback = callback;
  });

  m.def("set_column_hidden", [](int pane, int column, bool hidden) {
    Session& s = session();
    if (pane >= 0 && pane < 3 && s.views[pane] != nullptr) {
      s.views[pane]->setColumnHidden(column, hidden);
    }
  });

  m.def("is_column_hidden", [](int pane, int column) {
    Session& s = session();
    return pane >= 0 && pane < 3 && s.views[pane] != nullptr
               ? s.views[pane]->isColumnHidden(column) : true;
  });

  m.def("collapse_all", [](bool value) {
    Session& s = session();
    for (std::size_t i = 0; i < s.store.collapsed.size(); ++i) {
      s.store.collapsed[i] = value ? 1 : 0;
    }
    auto root_it = s.store.path_to_id.find(DataStore::root_path());
    if (root_it != s.store.path_to_id.end() &&
        root_it->second < static_cast<int>(s.store.collapsed.size())) {
      s.store.collapsed[root_it->second] = 0;
    }
    s.store.rebuild_visible();
    refresh_native_models(s);
  });

  m.def("decision_for_path", [](const std::string& path) {
    Session& s = session();
    auto it = s.store.path_to_id.find(path);
    if (it == s.store.path_to_id.end()) return 0;
    const int id = it->second;
    return id < static_cast<int>(s.store.decisions.size())
               ? s.store.decisions[id] : 0;
  });

  m.def("is_collapsed_by_path", [](const std::string& path) {
    Session& s = session();
    auto it = s.store.path_to_id.find(path);
    if (it == s.store.path_to_id.end()) return false;
    const int id = it->second;
    return id < static_cast<int>(s.store.collapsed.size()) &&
           s.store.collapsed[id] != 0;
  });

  m.def("is_directory_by_path", [](const std::string& path) {
    Session& s = session();
    auto it = s.store.path_to_id.find(path);
    if (it == s.store.path_to_id.end()) return false;
    const int id = it->second;
    return id < static_cast<int>(s.store.is_dir.size()) && s.store.is_dir[id] != 0;
  });

  m.def("path_of_id", [](int path_id) {
    Session& s = session();
    return path_id >= 0 && path_id < static_cast<int>(s.store.paths.size())
               ? s.store.paths[path_id] : std::string();
  });

  m.def("path_id_for_path", [](const std::string& path) {
    Session& s = session();
    auto it = s.store.path_to_id.find(path);
    return it != s.store.path_to_id.end() ? it->second : -1;
  });

  m.def("reset_decisions", [](const std::string& prefix, bool subtree) {
    Session& s = session();
    for (int i = 0; i < static_cast<int>(s.store.decisions.size()); ++i) {
      const std::string& path = i < static_cast<int>(s.store.paths.size())
                                    ? s.store.paths[i] : std::string();
      bool hit = prefix.empty() ? true
                 : subtree ? (path.compare(0, prefix.size(), prefix) == 0 &&
                              path.size() > prefix.size() && path[prefix.size()] == '/')
                           : path == prefix;
      if (!hit) continue;
      s.store.decisions[i] = Inherit;
      s.store.decision_log.emplace_back(i, Inherit);
    }
    s.store.rebuild_visible();
    refresh_native_models(s);
  });

  m.def("set_decision_by_path", [](const std::string& path, int decision) {
    Session& s = session();
    auto it = s.store.path_to_id.find(path);
    if (it == s.store.path_to_id.end()) return;
    const int id = it->second;
    s.store.set_decision_id(id, decision, true);
    if (g_native_decision_hook != nullptr) {
      // Python mirrors the decision and calls refresh_after_decision(); doing
      // the same refresh here cost another full pass over half a million rows.
      g_native_decision_hook(id, decision);
    } else {
      s.store.rebuild_visible();
      refresh_native_models(s);
    }
  });

  m.def("set_action_icons", [](const std::vector<std::uintptr_t>& pointers) {
    Session& s = session();
    s.action_icons.clear();
    for (std::uintptr_t pointer : pointers) {
      if (pointer == 0) {
        s.action_icons.emplace_back();
        continue;
      }
      s.action_icons.push_back(*reinterpret_cast<QIcon*>(pointer));
    }
    for (TableModel* model : s.models) model->layout_refresh();
    update_stats(s);
  });

  m.def("set_name_icons", [](std::uintptr_t folder, std::uintptr_t root,
                             const std::vector<std::pair<std::string, std::uintptr_t>>& files) {
    Session& s = session();
    auto icon_of = [](std::uintptr_t pointer) {
      return pointer == 0 ? QIcon() : *reinterpret_cast<QIcon*>(pointer);
    };
    s.store.folder_icon = icon_of(folder);
    s.store.root_icon = icon_of(root);
    s.store.file_icons.clear();
    for (const auto& entry : files) {
      s.store.file_icons[entry.first] = icon_of(entry.second);
    }
    for (TableModel* model : s.models) model->layout_refresh();
  });

  m.def("set_action_colours", [](const std::vector<std::string>& colours) {
    Session& s = session();
    s.action_colours.clear();
    for (const std::string& value : colours) {
      s.action_colours.push_back(QString::fromStdString(value));
    }
    s.store.action_colours = s.action_colours;
    for (TableModel* model : s.models) model->layout_refresh();
  });

  m.def("set_profiling_enabled", [](bool value) { g_profiling_enabled = value; });

  m.def("set_root_names", [](const std::string& source,
                             const std::string& destination) {
    Session& s = session();
    if (s.store.root_source == source && s.store.root_dest == destination) {
      return;
    }
    s.store.root_source = source;
    s.store.root_dest = destination;
    if (s.store.path_to_id.count(DataStore::root_path())) {
      int root = s.store.path_to_id[DataStore::root_path()];
      if (root < static_cast<int>(s.store.names.size())) {
        s.store.names[root] = source;
      }
    }
    for (TableModel* model : s.models) model->layout_refresh();
  });

  m.def("set_action_filter", [](int mask) { session().store.action_mask = mask; });

  m.def("set_pattern", [](const std::string& pattern, bool glob,
                          bool dirs_only, bool include_contents) {
    Session& s = session();
    s.store.pattern = pattern;
    s.store.pattern_glob = glob;
    s.store.dirs_only = dirs_only;
    s.store.include_contents = include_contents;
  });

  m.def("set_collapsed", [](int path_id, bool value) {
    session().store.set_collapsed(path_id, value);
  });

  m.def("set_collapsed_by_path", [](const std::string& path, bool value) {
    Session& s = session();
    auto it = s.store.path_to_id.find(path);
    if (it != s.store.path_to_id.end()) s.store.set_collapsed(it->second, value);
  });

  m.def("set_sort", [](int column, bool descending) {
    Session& s = session();
    s.store.sort_column = column;
    s.store.sort_desc = descending;
  });

  m.def("refresh_visible", []() {
    Session& s = session();
    s.store.rebuild_visible();
    refresh_native_models(s);
    update_stats(s);
  });

  m.def("set_show_excluded", [](bool show) {
    Session& s = session();
    s.store.show_excluded = show;
    s.store.rebuild_visible();
    refresh_native_models(s);
    update_stats(s);
  });

  m.def("apply_python_decisions", [](const std::vector<std::pair<int, int>>& pairs) {
    Session& s = session();
    std::vector<int> target(s.store.decisions.size(), Inherit);
    for (const auto& pair : pairs) {
      if (pair.first >= 0 && pair.first < static_cast<int>(target.size())) {
        target[pair.first] = pair.second;
      }
    }
    int changed_id = -1;
    int changed_count = 0;
    for (std::size_t i = 0; i < target.size(); ++i) {
      if (target[i] == s.store.decisions[i]) continue;
      ++changed_count;
      changed_id = static_cast<int>(i);
      s.store.decisions[i] = target[i];
    }
    s.store.decision_log.clear();
    if (changed_count == 1 &&
        s.store.update_single_visibility(changed_id, target[changed_id])) {
      refresh_native_models(s);
      update_stats(s);
    } else if (changed_count > 0) {
      s.store.rebuild_visible();
      refresh_native_models(s);
      update_stats(s);
    }
  });

  m.def("refresh_after_decision", [](int path_id, int decision) {
    Session& s = session();
    QElapsedTimer total_timer;
    total_timer.start();
    QElapsedTimer phase;
    phase.start();
    s.store.rebuild_visible();
    if (profiling_enabled()) {
      std::fprintf(stderr, "[qpy-rsync native] rebuild_visible ms=%lld\n",
                   static_cast<long long>(phase.elapsed()));
    }
    refresh_native_models(s);
    QElapsedTimer stats_timer;
    stats_timer.start();
    update_stats(s);
    if (profiling_enabled()) {
      std::fprintf(stderr, "[qpy-rsync native] update_stats ms=%lld total=%lld\n",
                   static_cast<long long>(stats_timer.elapsed()),
                   static_cast<long long>(total_timer.elapsed()));
    }
  });

  m.def("refresh", []() {
    Session& s = session();
    s.store.add_directories();
    s.store.rebuild_visible();
    if (s.tables_widget == nullptr) {
      // Standalone callers may not have created widgets yet.
      return;
    }
    refresh_native_models(s, true);
    update_stats(s);
  });

  m.def("selected_path", []() {
    Session& s = session();
    if (s.views[0] == nullptr || s.views[0]->selectionModel() == nullptr) return std::string();
    QModelIndexList rows = s.views[0]->selectionModel()->selectedRows();
    if (rows.isEmpty()) return std::string();
    int row = rows.first().row();
    if (row < 0 || row >= static_cast<int>(s.store.visible.size())) return std::string();
    const int id = s.store.visible[row];
    return s.store.paths[id] == DataStore::root_path() ? std::string()
                                                       : s.store.paths[id];
  });

  m.def("selected_paths", []() {
    Session& s = session();
    std::vector<std::string> result;
    for (QTableView* view : s.views) {
      if (view == nullptr || view->selectionModel() == nullptr) continue;
      const QModelIndexList rows = view->selectionModel()->selectedRows();
      if (rows.isEmpty()) continue;
      for (const QModelIndex& index : rows) {
        const int row = index.row();
        if (row < 0 || row >= static_cast<int>(s.store.visible.size())) continue;
        const int id = s.store.visible[row];
        if (id < 0 || id >= static_cast<int>(s.store.paths.size())) continue;
        const std::string& path = s.store.paths[id];
        if (path == DataStore::root_path()) continue;
        result.push_back(path);
      }
      break;
    }
    return result;
  });

  m.def("path_of_row", [](int row) {
    Session& s = session();
    if (row < 0 || row >= static_cast<int>(s.store.visible.size())) return std::string();
    const int id = s.store.visible[row];
    return s.store.paths[id] == DataStore::root_path() ? std::string()
                                                       : s.store.paths[id];
  });

  m.def("search_text", [](const std::string& text) {
    Session& s = session();
    if (text.size() > 1 && text.back() == '/') {
      std::string name = text.substr(0, text.size() - 1);
      const bool by_path = name.find('/') != std::string::npos;
      std::vector<int> result;
      for (int row = 0; row < static_cast<int>(s.store.visible.size()); ++row) {
        int id = s.store.visible[row];
        if (id >= static_cast<int>(s.store.is_dir.size()) || !s.store.is_dir[id]) continue;
        const std::string& candidate = by_path ? s.store.folded_paths[id]
                                               : s.store.folded_names[id];
        if (candidate == name) result.push_back(row);
      }
      return result;
    }
    return s.store.search(text);
  });

  m.def("toggle_decision", [](int path_id) { session().store.toggle_decision(path_id); });

  m.def("set_checkstate", [](int row, int checked) {
    Session& s = session();
    if (s.models[1] == nullptr) return;
    QModelIndex index = s.models[1]->index(row, 4);
    s.models[1]->setData(
        index, checked ? Qt::Checked : Qt::Unchecked, Qt::CheckStateRole);
  });

  m.def("decision_diff", []() { return session().store.decision_log; });
}
