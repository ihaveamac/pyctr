{
  lib,
  buildPythonPackage,
  pythonOlder,
  pycryptodomex,
  pillow,
  fsspec,
}:

let
    version = (builtins.fromJSON(builtins.readFile ./pyctr/version.json)).version;
in
buildPythonPackage {
  inherit version;
  pname = "pyctr";
  pyproject = true;

  disabled = pythonOlder "3.12";

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
    fsspec
    pillow
  ];

  pythonImportsCheck = [
    "pyctr"
  ];
}
