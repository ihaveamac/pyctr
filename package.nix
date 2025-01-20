{
  lib,
  buildPythonPackage,
  pythonOlder,
  pycryptodomex,
  pillow,
  fs,
  pyfatfs,
}:

buildPythonPackage {
  pname = "pyctr";
  version = "0.8-beta";
  pyproject = true;

  disabled = pythonOlder "3.8";

  src = builtins.path {
    path = ./.;
    name = "pyctr";
    filter =
      path: type:
      !(builtins.elem (baseNameOf path) [
        "build"
        "dist"
        "localtest"
        "__pycache__"
        "v"
        ".git"
        "_build"
        "pyctr.egg-info"
      ]);
  };

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
