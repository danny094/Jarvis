You need a virtual Python environment; if you already have one, skip to point 2.

(Ubuntu)
1. python3-venv
* sudo apt-get install python3-venv 
* python3 -m venv /home/USER/venv-test 

***You need the same packages as the main project.***

2. In the virtual environment:
* source /home/USER/venv-test/bin/activate 
* pip install -r requirements.txt
* pip install -r requirements-dev.txt

3. run pytest
