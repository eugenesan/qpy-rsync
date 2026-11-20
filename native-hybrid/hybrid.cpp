// Production bridge for the hybrid app: Python owns rsync/parsing/validation,
// native Qt owns the view models and the volatile decision table.

#include <nanobind/nanobind.h>
#include <nanobind/stl/pair.h>
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
#include <QLabel>
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
#include <string>
#include <vector>

#include "model.hpp"

namespace nb = nanobind;

namespace {
struct Session {
  DataStore store;
  QWidget* widget = nullptr;  // legacy combined widget
  QWidget* tables_widget = nullptr;
  QWidget* overview_widget = nullptr;
  QTreeView* overview_view = nullptr;
  QLabel* stats_label = nullptr;
  std::vector<QString> action_colours;
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
inline nb::object g_selection_callback;
inline nb::object g_decision_callback;
inline nb::object g_context_callback;

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

void refresh_native_models(Session& s) {
  int positions[3] = {0, 0, 0};
  for (int i = 0; i < 3; ++i) {
    if (s.views[i] != nullptr && s.views[i]->verticalScrollBar() != nullptr) {
      positions[i] = s.views[i]->verticalScrollBar()->value();
    }
  }
  for (TableModel* model : s.models) model->reset();
  for (int i = 0; i < 3; ++i) {
    if (s.views[i] != nullptr && s.views[i]->verticalScrollBar() != nullptr) {
      s.views[i]->verticalScrollBar()->setValue(positions[i]);
    }
  }
}

void select_path_id_impl(Session& s, int path_id) {
  if (path_id < 0 || path_id >= static_cast<int>(s.store.row_of_id.size())) return;
  int row = s.store.row_of_id[path_id];
  g_in_select = true;
  for (QTableView* view : s.views) {
    if (view == nullptr || view->model() == nullptr) continue;
    QModelIndex index = view->model()->index(row, 0);
    if (!index.isValid()) continue;
    view->selectionModel()->select(
        index, QItemSelectionModel::ClearAndSelect | QItemSelectionModel::Rows);
    view->scrollTo(index);
  }
  g_in_select = false;
  emit_selection(path_id);
}

class HybridDelegate : public QStyledItemDelegate {
 public:
  HybridDelegate(Session* session, int pane, QObject* parent = nullptr)
      : QStyledItemDelegate(parent), session_(session), pane_(pane) {}

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

    const bool name_col = (col == 0 || col == 5);
    QStyleOptionViewItem opt(option);
    initStyleOption(&opt, index);
    const bool selected = opt.state & QStyle::State_Selected;
    const bool striped = !selected && row < static_cast<int>(store.stripe.size()) &&
                         store.stripe[row] != 0;
    if (!name_col) {
      QStyledItemDelegate::paint(painter, opt, index);
      return;
    }
    // QStyledItemDelegate::paint re-reads the text from the model, so draw the
    // background ourselves and lay out the name cell explicitly.
    paint_background(painter, option, striped);

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
    if (is_dir) {
      const bool expanded = !(id < static_cast<int>(store.collapsed.size()) &&
                              store.collapsed[id]);
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
      draw_folder_icon(painter, QRect(x + 12, mid - 7, 14, 12));
      x += 30;
    } else {
      painter->setPen(QPen(QColor("#D0D7DE"), 1));
      const int rule = x + 4;
      painter->drawLine(rule, opt.rect.top(), rule, opt.rect.bottom());
      draw_file_icon(painter, QRect(x + 12, mid - 8, 12, 14), color);
      x += 30;
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
    if (striped) painter->fillRect(blank.rect, QColor("#F1F3F5"));
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
    const QWidget* widget = option.widget;
    QStyle* style = widget != nullptr ? widget->style() : QApplication::style();
    QStyleOptionButton indicator;
    indicator.state = option.state;
    indicator.state &= ~QStyle::State_MouseOver;
    indicator.rect = QRect(opt.rect.left() + 4, opt.rect.center().y() - 7, 14, 14);
    const bool checked = index.data(Qt::CheckStateRole).toInt() == Qt::Checked;
    if (checked) indicator.state |= QStyle::State_On;
    else indicator.state |= QStyle::State_Off;
    style->drawPrimitive(QStyle::PE_IndicatorItemViewItemCheck, &indicator,
                         painter, widget);
    if (id >= static_cast<int>(store.actions.size())) return;
    const int action = store.actions[id];
    QColor color("#9CA3AF");
    if (action >= 0 && action < static_cast<int>(s.action_colours.size())) {
      const QString hex = s.action_colours[action];
      if (!hex.isEmpty()) color = QColor(hex);
    }
    const int x = opt.rect.left() + 34;
    const int y = opt.rect.center().y();
    painter->save();
    if (action == Delete) {
      painter->setPen(QPen(color, 2));
      painter->drawLine(x - 4, y - 4, x + 4, y + 4);
      painter->drawLine(x + 4, y - 4, x - 4, y + 4);
    } else if (action == NoChange) {
      painter->setPen(QPen(color, 2));
      painter->drawLine(x - 4, y, x - 1, y + 3);
      painter->drawLine(x - 1, y + 3, x + 5, y - 4);
    } else {
      painter->setPen(Qt::NoPen);
      painter->setBrush(color);
      QPoint pts[3] = {{x, y - 5}, {x + 5, y + 3}, {x - 5, y + 3}};
      painter->drawPolygon(pts, 3);
    }
    painter->restore();
  }

  Session* session_;
  int pane_;
};

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
      views[i]->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOn);
      splitter->addWidget(views[i]);
    }
    for (int i = 0; i < 3; ++i) s.views[i] = views[i];
    s.models[0] = new TableModel(&s.store, 0, s.tables_widget);
    s.models[1] = new TableModel(&s.store, 1, s.tables_widget);
    s.models[2] = new TableModel(&s.store, 2, s.tables_widget);
    views[0]->setModel(s.models[0]);
    views[1]->setModel(s.models[1]);
    views[2]->setModel(s.models[2]);
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
    views[1]->horizontalHeader()->resizeSection(4, 72);
    for (QTableView* view : views) {
      view->horizontalHeader()->setFixedHeight(
          qMax(16, view->fontMetrics().height() + 2));
      view->setAlternatingRowColors(false);
    }
    for (int i = 0; i < 3; ++i) {
      views[i]->setItemDelegate(new HybridDelegate(&s, i, s.tables_widget));
      views[i]->setContextMenuPolicy(Qt::CustomContextMenu);
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
              emit_selection(current.store.visible[row]);
            }
          });
    }
    splitter->setStretchFactor(0, 1);
    splitter->setStretchFactor(1, 0);
    splitter->setStretchFactor(2, 1);
    QSizePolicy policy = views[1]->sizePolicy();
    policy.setHorizontalPolicy(QSizePolicy::Fixed);
    views[1]->setSizePolicy(policy);
    views[1]->setFixedWidth(72);
    s.tables_widget->setMinimumWidth(700);
  }
  return s.tables_widget;
}

QWidget* ensure_overview_widget(Session& s) {
  if (s.overview_widget == nullptr) {
    s.overview_widget = new QWidget();
    auto* layout = new QVBoxLayout(s.overview_widget);
    layout->setContentsMargins(0, 0, 0, 0);
    s.stats_label = new QLabel(s.overview_widget);
    s.stats_label->setWordWrap(true);
    s.overview_view = new QTreeView(s.overview_widget);
    s.overview_view->setUniformRowHeights(true);
    s.overview_view->setAlternatingRowColors(true);
    s.overview_view->setRootIsDecorated(true);
    s.overview_view->header()->setStretchLastSection(false);
    s.overview_view->header()->setSectionResizeMode(0, QHeaderView::Stretch);
    s.overview_view->header()->setSectionResizeMode(1, QHeaderView::Fixed);
    s.overview_view->header()->resizeSection(1, 56);
    s.overview_view->header()->setSectionResizeMode(2, QHeaderView::Fixed);
    s.overview_view->header()->resizeSection(2, 64);
    s.overview_view->header()->setSectionResizeMode(3, QHeaderView::Fixed);
    s.overview_view->header()->resizeSection(3, 84);
    s.overview = new OverviewModel(s.overview_widget);
    s.overview_view->setModel(s.overview);
    s.overview_view->expandToDepth(2);
    layout->addWidget(s.overview_view);
    layout->addWidget(s.stats_label);
    QObject::connect(
        s.overview_view, &QTreeView::doubleClicked,
        [](const QModelIndex& index) {
          Session& current = session();
          QString path = current.overview->data(index, Qt::UserRole).toString();
          auto it = current.store.path_to_id.find(path.toStdString());
          if (it != current.store.path_to_id.end()) {
            select_path_id_impl(current, it->second);
          }
        });
  }
  return s.overview_widget;
}

void update_stats(Session& s) {
  if (s.stats_label == nullptr) return;
  long long count = 0, size = 0, creates = 0, updates = 0, deletes = 0;
  for (int id : s.store.visible) {
    if (id < 0 || id >= static_cast<int>(s.store.is_dir.size())) continue;
    if (s.store.is_dir[id]) continue;
    ++count;
    size += id < static_cast<int>(s.store.sizes.size()) ? s.store.sizes[id] : 0;
    int action = id < static_cast<int>(s.store.actions.size())
                     ? s.store.actions[id] : NoChange;
    if (action == Create) ++creates;
    else if (action == Update || action == Metadata) ++updates;
    else if (action == Delete) ++deletes;
  }
  s.stats_label->setText(
      QString("%1 item(s), %2   + %3   ↑ %4   ✗ %5")
          .arg(count).arg(qpy_format_size(size))
          .arg(creates).arg(updates).arg(deletes));
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

  m.def("set_action_colours", [](const std::vector<std::string>& colours) {
    Session& s = session();
    s.action_colours.clear();
    for (const std::string& value : colours) {
      s.action_colours.push_back(QString::fromStdString(value));
    }
    s.store.action_colours = s.action_colours;
    for (TableModel* model : s.models) model->layout_refresh();
  });

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
      for (TableModel* model : s.models) model->layout_refresh();
      update_stats(s);
    } else if (changed_count > 0) {
      s.store.rebuild_visible();
      refresh_native_models(s);
      update_stats(s);
    }
  });

  m.def("refresh_after_decision", [](int path_id, int decision) {
    Session& s = session();
    if (decision != Exclude) return;
    s.store.rebuild_visible();
    refresh_native_models(s);
    update_stats(s);
  });

  m.def("refresh", []() {
    Session& s = session();
    s.store.add_directories();
    s.store.rebuild_visible();
    if (s.tables_widget == nullptr) {
      // Standalone callers may not have created widgets yet.
      return;
    }
    if (s.overview != nullptr) {
      s.overview->build(s.store);
      s.overview_view->expandToDepth(2);
    }
    refresh_native_models(s);
    update_stats(s);
  });

  m.def("selected_path", []() {
    Session& s = session();
    if (s.views[0] == nullptr || s.views[0]->selectionModel() == nullptr) return std::string();
    QModelIndexList rows = s.views[0]->selectionModel()->selectedRows();
    if (rows.isEmpty()) return std::string();
    int row = rows.first().row();
    if (row < 0 || row >= static_cast<int>(s.store.visible.size())) return std::string();
    return s.store.paths[s.store.visible[row]];
  });

  m.def("path_of_row", [](int row) {
    Session& s = session();
    if (row < 0 || row >= static_cast<int>(s.store.visible.size())) return std::string();
    return s.store.paths[s.store.visible[row]];
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
