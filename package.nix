{ buildPythonPackage, pythonOlder, pycryptodomex, pillow, fs, pyfatfs }:

buildPythonPackage {
  pname = "pyctr";
  version = "0.8-beta";
  pyproject = true;

  disabled = pythonOlder "3.8";

  src = builtins.path { path = ./.; name = "pyctr"; };

  propagatedBuildInputs = [
    pycryptodomex
    fs
    pyfatfs
    pillow
  ];

  pythonImportsCheck = [
    "pyctr"
  ];
}
