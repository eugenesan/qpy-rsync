from qpy_rsync.core.execution_plan import PlanSummary
from qpy_rsync.gui.workflow_state import selected_actions_text, startup_message, swapped_endpoint_texts


def test_startup_messages() -> None:
    assert "Click Compare" in startup_message(True, True)
    assert "Choose Source and Destination" in startup_message(True, False)


def test_selected_actions_text() -> None:
    summary = PlanSummary(12, 2, 0, 1, 3, 7, 1, 0, 1, True)
    assert selected_actions_text(summary) == (
        "Selected actions: 12 included, 2 excluded, 1 destructive | Backup: on"
    )


def test_swap_endpoint_texts() -> None:
    assert swapped_endpoint_texts("/src/", "nas:/dst/") == ("nas:/dst/", "/src/")
