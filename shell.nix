{ pkgs ? import <nixpkgs> {}, withPyctr ? false }:

let
  pyctrPkgs = import ./default.nix { inherit pkgs; };
  pyctr = pyctrPkgs.pyctr;
  pythonPackages = pkgs.python3Packages;
in pkgs.mkShell {
  name = "pyctr-dev-shell";

  packages = pyctr.propagatedBuildInputs ++ [
    pythonPackages.pytest
  ] ++ (pkgs.lib.optional withPyctr pyctr);

  shellHook = ''
    # pytest seems to have issues without doing this
    PYTHONPATH=$PWD:$PYTHONPATH
  '';
}
