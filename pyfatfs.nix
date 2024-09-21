{ lib, buildPythonPackage, pythonOlder, fetchPypi, fs, pip, setuptools, setuptools-scm }:

buildPythonPackage rec {
  pname = "pyfatfs";
  version = "1.1.0";
  pyproject = true;

  disabled = pythonOlder "3.6";

  src = fetchPypi {
    inherit pname version;
    hash = "sha256-lyXM0KTaHAnCc1irvxDwjAQ6yEIQr1doA+CH9RorMOA=";
  };

  doCheck = false;

  patches = [ ./pyfatfs-fix-deps.patch ];

  buildInputs = [ setuptools setuptools-scm ];

  propagatedBuildInputs = [
    fs
    setuptools
    setuptools-scm
    #pip
  ];

  pythonImportsCheck = [
    "pyfatfs"
  ];
}
