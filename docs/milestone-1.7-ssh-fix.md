# milestone 1.7 SSH askpass display fix

The previous release forced `LC_ALL=C` for rsync output. A Qt 6 askpass helper interprets that as the non-UTF-8 `ANSI_X3.4-1968` locale. In a Wayland-only Plasma session, the helper could also select the xcb plugin despite having no `DISPLAY`, aborting before host-key or password interaction.

qpy-rsync no longer overrides the locale. Its controlled itemized record format does not need locale-dependent parsing. When `WAYLAND_DISPLAY` is available and `QT_QPA_PLATFORM` is not already explicit, the askpass child receives:

```text
QT_QPA_PLATFORM=wayland
```

The complete inherited desktop environment still supplies `WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR`, and `DBUS_SESSION_BUS_ADDRESS` through `QProcessEnvironment.systemEnvironment()`.

If neither Wayland nor X11 session variables are present, password authentication is blocked before rsync starts. SSH key authentication through an already unlocked agent remains the preferred future path, but milestone 1.7 still requires askpass discovery for every remote profile.
