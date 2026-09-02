# ExplainDB — Database Systems Materials

## Setting Up the Environment with Pipenv

### 0. Clone the Repository

Open a terminal (macOS/Linux) or Command Prompt/PowerShell (Windows) and run the following command:
- **macOS/Linux/Windows**:
    ```sh
    git clone https://gitlab.cs.uni-saarland.de:bigdata/dbsys/explaindb.git
    ```

### 1. Install Python 3.12

This repository strictly requires Python 3.12.
- **macOS/Linux**: Install Python using your system's package manager like `brew` (macOS) or `apt`, `pacman` (Linux). For example:
    ```sh
    brew install python@3.12
    ```
    or
    ```sh
    sudo pacman -S python
    ```
    Note that depending on the Linux distribution, manual installation may be required.
- **Windows**: Download and install Python from the [official website](https://www.python.org/downloads/). Make sure to check the option to "Add Python to PATH"
  during installation.

### 2. Install Pipenv

Install `pipenv` using `pip` by running the following command.
- **macOS/Linux**:
    ```sh
    pip install --user pipenv
    ```
- **Windows**: Open a Command Prompt or PowerShell window with Administrator priviledges and run:
    ```sh
    pip install pipenv
    ```

### 3. Install Dependencies

Navigate to the cloned repository folder, where the `Pipfile` and `Pipfile.lock` are located, and run the following
command.
- **macOS/Linux/Windows**:
    ```sh
    pipenv install
    ```
This will create a virtual environment and install all required packages.

### 4. Activate the Virtual Environment

To activate the environment and use the installed dependencies, run the following command.
- **macOS/Linux/Windows**:
    ```sh
    pipenv shell
    ```

### 5. Running Jupyter Notebook

To start a Jupyter server and run Notebooks, execute the following command
- **macos/Linux/Windows**: **with** activated virtual environment
    ```sh
    jupyter notebook
    ```
    or **without** activated virtual environment
    ```sh
    pipenv run jupyter notebook
    ```
This should open a browser window listing the files in the current directory.

Alternatively, you may also run Jupyter
notebooks in an IDE like [PyCharm](https://www.jetbrains.com/pycharm/). See [here](https://www.jetbrains.com/help/pycharm/pipenv.html) for instructions on configuring a pipenv environment in PyCharm and [here](https://www.jetbrains.com/help/pycharm/jupyter-notebook-support.html) for information on Jupyter notebook support in PyCharm.

### 6. Deactivate the Virtual Environment

To deactivate the virtual environment, simply run:
- **macOS/Linux/Windows**:
    ```sh
    exit
    ```
