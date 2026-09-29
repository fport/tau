# tau-example-tool

Test fixture for tau-core. It is a separate distribution that declares one tool,
`example_echo` (tier 0), under the `tau.tools` entry point group. The workspace installs it
in the `dev` dependency group so `tests/test_plugins.py` can prove that a tool shipped by
another installed distribution is discovered without any change to tau-core.

Not published.
