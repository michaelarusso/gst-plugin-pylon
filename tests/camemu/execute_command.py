#!/usr/bin/env python3
"""Verify the pylonsrc execute-command action signal runs GenICam commands.

The camera is configured for software triggering, so frames only arrive when
the TriggerSoftware command is executed through the signal. This proves the
command actually reaches the camera, not just that the signal returns TRUE.
"""

import argparse
import sys
import time

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

TRIGGER_ARGS = ("TriggerSoftware", "TriggerSelector", "FrameStart")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--triggers", type=int, default=5)
    return parser.parse_args()


def execute(src, command, selector=None, selector_value=None):
    return src.emit("execute-command", command, selector, selector_value)


def main():
    args = parse_args()
    Gst.init(None)
    failures = []

    def check(condition, message):
        if not condition:
            failures.append(message)

    # A command on an element without an open camera must fail, not crash.
    idle = Gst.ElementFactory.make("pylonsrc", None)
    check(not execute(idle, *TRIGGER_ARGS),
          "execute-command succeeded without an open camera")

    pipeline = Gst.parse_launch(
        "pylonsrc name=src device-serial-number={serial} "
        "cam::TriggerMode-FrameStart=On "
        "cam::TriggerSource-FrameStart=Software "
        "! video/x-raw,format=GRAY8,width=640,height=480 "
        "! appsink name=sink emit-signals=false sync=false "
        "max-buffers=1 drop=false".format(serial=args.serial)
    )
    src = pipeline.get_by_name("src")
    sink = pipeline.get_by_name("sink")

    pipeline.set_state(Gst.State.PLAYING)
    try:
        # Grabbing starts asynchronously after caps negotiation, so keep
        # triggering until the first frame arrives.
        deadline = time.monotonic() + 10
        armed = False
        while time.monotonic() < deadline:
            execute(src, *TRIGGER_ARGS)
            if sink.emit("try-pull-sample", 200 * Gst.MSECOND) is not None:
                armed = True
                break
        check(armed, "no frame arrived after software triggers during warm-up")

        if armed:
            # Drain anything a warm-up trigger may still have in flight.
            while sink.emit("try-pull-sample", 200 * Gst.MSECOND) is not None:
                pass

            check(sink.emit("try-pull-sample", 500 * Gst.MSECOND) is None,
                  "frame arrived without a software trigger")

            for i in range(args.triggers):
                check(execute(src, *TRIGGER_ARGS),
                      "TriggerSoftware returned FALSE (trigger {})".format(i))
                check(sink.emit("try-pull-sample", 5 * Gst.SECOND) is not None,
                      "no frame after software trigger {}".format(i))

        check(not execute(src, "NoSuchCommand"),
              "unknown command did not fail")
        check(not execute(src, "Gain"),
              "non-command feature did not fail")
        check(not execute(src, "TriggerSoftware", "NoSuchSelector", "X"),
              "unknown selector did not fail")
        check(not execute(src, "TriggerSoftware", "TriggerSelector",
                          "NoSuchTrigger"),
              "invalid selector value did not fail")
        check(not execute(src, "TriggerSoftware", "TriggerSelector", None),
              "selector without a value did not fail")
    finally:
        pipeline.set_state(Gst.State.NULL)

    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
