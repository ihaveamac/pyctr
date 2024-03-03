{ lib, buildPythonPackage, pythonOlder, fetchPypi, fs, pip }:

buildPythonPackage rec {
  pname = "pyfatfs";
  version = "1.0.5";
  format = "setuptools";

  disabled = pythonOlder "3.6";

  src = fetchPypi {
    inherit pname version;
    hash = "sha256-5J6gYhGf32GYx7u8/ghYnYkZ40rCH19gTQ7YtcREly0=";
  };

  doCheck = false;

  propagatedBuildInputs = [
    fs
    pip
  ];

  pythonImportsCheck = [
    "pyfatfs"
  ];
}
