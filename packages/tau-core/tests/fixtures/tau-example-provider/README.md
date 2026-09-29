# tau-example-provider

Test fixture for tau-core. It is a separate distribution that declares:

- a `tau.providers` entry point `fake2` (a scripted `FakeModel` that needs the
  `EXAMPLE_API_KEY` variable, declared through the factory's `required_env` attribute);
- a `tau.sessions` entry point `example` (an in-memory store).

The workspace installs it in the `dev` dependency group so `tests/test_registry.py` and
`tests/test_builder.py` can prove that providers and session backends shipped by another
installed distribution are discovered without any change to tau-core.

Not published.
