# milestone 1.8 X11 askpass fix

The milestone 1.7 trace showed `QT_QPA_PLATFORM=xcb` but the askpass error printed an empty display name. qpy-rsync therefore now explicitly inserts these inherited desktop values into the `QProcess` environment rather than depending only on implicit inheritance:

```text
DISPLAY
XAUTHORITY
DBUS_SESSION_BUS_ADDRESS
XDG_RUNTIME_DIR
WAYLAND_DISPLAY
```

For the reported Plasma X11 environment the debug record should contain at least:

```text
DISPLAY=:0
XAUTHORITY=/run/user/1000/xauth_...
QT_QPA_PLATFORM=xcb
```

This is intentionally visible in debug mode so display authentication can be diagnosed precisely. These values are session endpoints, not passwords, though paths and usernames should still be reviewed before sharing logs.
