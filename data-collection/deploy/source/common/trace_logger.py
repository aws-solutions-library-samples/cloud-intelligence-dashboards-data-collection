"""
CID Trace Logger

Adds a ``TRACE`` level one step below ``DEBUG`` (5, vs. ``DEBUG``'s 10), for
detail that is too expensive or too verbose to render at every DEBUG call.

``TraceLogger.debug`` accepts an optional ``trace=`` argument: the normal
message/args are always logged at DEBUG, and ``trace`` is only rendered (via
``trace()``, at the TRACE level) when TRACE is actually enabled. This lets a
caller log a cheap summary at DEBUG and defer the expensive full value to
TRACE without a separate ``if logger.isEnabledFor(...)`` guard at each call
site:

    logger.debug("Collected %d records", len(records), trace=records)

At ``LOG_LEVEL=DEBUG`` this logs only ``Collected 42 records``. At
``LOG_LEVEL=TRACE`` it additionally logs ``Collected 42 records -> [...]``
with ``records`` rendered in full.
"""

import logging

TRACE = 5
logging.addLevelName(TRACE, "TRACE")
# So callers can resolve "TRACE" the same way they resolve "DEBUG"/"INFO",
# e.g. getattr(logging, os.environ["LOG_LEVEL"].upper()).
logging.TRACE = TRACE


class TraceLogger(logging.Logger):
    """``logging.Logger`` subclass with a TRACE level and a debug shorthand."""

    def trace(self, msg, *args, **kwargs):
        """Log at TRACE (5) — one level more granular than DEBUG."""
        if self.isEnabledFor(TRACE):
            self._log(TRACE, msg, args, **kwargs)  # pylint: disable=protected-access

    def debug(self, msg, *args, trace=None, **kwargs):
        """Log at DEBUG, optionally deferring a fuller render to TRACE.

        Args:
            trace: When given, also logged at TRACE as ``"<msg> -> %s"`` with
                ``trace`` rendered via its ``%s`` conversion. Building this
                extra call is cheap; rendering ``trace`` itself only happens
                if TRACE is enabled, since ``trace()`` checks the level
                before formatting.
        """
        super().debug(msg, *args, **kwargs)
        if trace is not None:
            self.trace(msg + " -> %s", *args, trace, **kwargs)

    def auto(self, *, trace=None, debug=None, info=None, warning=None, error=None, critical=None):
        """Log at any subset of levels in a single call.

        Each kwarg maps to this logger's own method of the same name. When
        given, that method is called with the value as the message; each
        dedicated method still gates on its own level as usual, so e.g. at
        INFO, ``debug=`` reaches ``self.debug()`` but produces no output.

            logger.auto(info="my info", debug="my debug")

        At ``LOG_LEVEL=INFO`` this logs ``my info`` only.
        """
        for level, msg in (
            ("trace", trace),
            ("debug", debug),
            ("info", info),
            ("warning", warning),
            ("error", error),
            ("critical", critical),
        ):
            if msg is not None:
                getattr(self, level)(msg)


def get_trace_logger(name=None):
    """Return a logger with TRACE support, regardless of creation order.

    Patches the live logger instance's ``__class__`` rather than relying on
    ``logging.setLoggerClass``, which only affects loggers created *after*
    it is called — so this works even if ``logging.getLogger(name)`` was
    already called elsewhere first (e.g. by a third-party library).

    Args:
        name: Logger name. Defaults to the root logger, same as
            ``logging.getLogger(None)``.
    """
    log = logging.getLogger(name)
    if not isinstance(log, TraceLogger):
        log.__class__ = TraceLogger
    return log
