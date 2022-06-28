Qualisys extension for Skybrush Server
======================================

This repository contains an experimental extension module to Skybrush Server
that adds support for Qualisys mocap systems for indoor drone tracking.

Installation
------------

1. Check out this repository using git.

2. Install [`poetry`](https://python-poetry.org) if you haven't done so yet;
   `poetry` is a tool that allows you to install Skybrush Server and the
   extension you are working on in a completely isolated virtual environment.

3. Run `poetry install`; this will create a virtual environment and install
   Skybrush Server with all required dependencies in it, as well as the code
   of the extension.

4. Run `poetry shell` to open a shell associated to the virtual environment
   that you have just created.

5. Modify `skybrushd.jsonc` to point to the host where the Qualisys Track
   Manager app is running.

6. In the shell prompt, type `skybrushd -c skybrushd.jsonc` to start the server
   with a configuration file that loads the extension.
