## Project setup.
The project uses [uv](https://github.com/astral-sh/uv) to manage dependencies and maintain the environment. `uv` uses a
`pyproject.toml` and `uv.lock` file to keep track of dependencies and manage various project-level settings. Clone the 
project from GitHub and then run the command `uv sync` from the project root folder. This will create a .venv
folder and download project dependencies. You must have `uv` installed globally to run this command.

## Running unit tests.
Unit tests for the project are located in the [/tests](/tests) folder. `pytest` is listed as a project dependency. 
To run unit tests, run `pytest test -v` from the project root folder. These tests should be run before every commit that
affects the project's functionality. [coverage](https://github.com/coveragepy/coveragepy)is a nice tool that can be used
to check whether code is covered in unit tests. `coverage` is not a "dependency" per ce but is a useful tool for 
developers that is useful for informing devs of which unit-tests are missing etc.

## Storing secrets.
Secrets should be stored in `secrets.env` in the project root folder. These include API keys, passwords etc. I.e
anything that you would not want anyone else to have access to. DO NOT COMMIT THIS FILE TO GIT.