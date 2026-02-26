import os
import signal

from utils import interruptible


def test_normal_iteration():
    """All items are yielded when no interrupt occurs."""
    assert list(interruptible([1, 2, 3])) == [1, 2, 3]


def test_stops_after_current_item_on_sigint():
    """First SIGINT lets the current item's loop body finish, then stops."""
    results = []
    for item in interruptible([1, 2, 3]):
        if item == 1:
            os.kill(os.getpid(), signal.SIGINT)
        # This runs even after SIGINT — the current iteration completes
        results.append(item)
    assert results == [1]


def test_double_sigint_raises():
    """Second SIGINT raises KeyboardInterrupt immediately."""
    results = []
    try:
        for item in interruptible([1, 2, 3]):
            results.append(item)
            if item == 1:
                os.kill(os.getpid(), signal.SIGINT)
                os.kill(os.getpid(), signal.SIGINT)
    except KeyboardInterrupt:
        pass
    assert results == [1]


def test_restores_original_handler():
    """Original SIGINT handler is restored after iteration."""
    original = signal.getsignal(signal.SIGINT)
    list(interruptible([1, 2, 3]))
    assert signal.getsignal(signal.SIGINT) is original


def test_restores_handler_after_interrupt():
    """Original SIGINT handler is restored even after an interrupt."""
    original = signal.getsignal(signal.SIGINT)
    for item in interruptible([1, 2, 3]):
        if item == 1:
            os.kill(os.getpid(), signal.SIGINT)
    assert signal.getsignal(signal.SIGINT) is original
