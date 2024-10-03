{ pkgs ? import <nixpkgs> {} }:

let
  pythonPackages = pkgs.python3Packages;
  pyctr = pythonPackages.callPackage ./pyctr.nix { };
in pkgs.mkShell {
  name = "pyctr-dev-shell";

  packages = pyctr.propagatedBuildInputs ++ [
    pythonPackages.pytest
  ];

  shellHook = ''
    # pytest seems to have issues without doing this
    PYTHONPATH=$PWD:$PYTHONPATH
  '';
}
