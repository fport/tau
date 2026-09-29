# tau-example-service

Test fixture for tau-core. It is a separate distribution that declares:

- a `tau.hub_services` entry point `example`: a `HubService` that adds an `example` key to
  the hub's `/status` payload and a `GET /example` route to the control API;
- a `tau.context` entry point `example`: a context source that reports the live nodes listed
  in the `[component.example] nodes` table of `tau.toml` (nothing configured = unknown).

The workspace installs it in the `dev` dependency group so `tests/test_registry.py`,
`tests/test_hub_daemon.py` and `tests/test_builder.py` can prove that hub services and context
sources shipped by another installed distribution are started, listed and switched off through
`[components]` without any change to tau-core.

Not published.
