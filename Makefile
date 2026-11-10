.PHONY: test installer install clean

test:
	python3 tests/test_core.py

installer:
	python3 tools/build_installer.py

install:
	./install.sh

clean:
	rm -rf dist __pycache__ tests/__pycache__
