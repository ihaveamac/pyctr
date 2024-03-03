{ buildPythonPackage, pythonOlder, pycryptodomex, pillow }:

buildPythonPackage {
  pname = "pyctr";
  version = "0.7-beta";
  format = "setuptools";

  disabled = pythonOlder "3.7";

  src = builtins.path { path = ./.; name = "pyctr"; };

  propagatedBuildInputs = [
    pycryptodomex
    pillow
  ];

  pythonImportsCheck = [
    "pyctr"
  ];
}
