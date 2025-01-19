{ pkgs ? import <nixpkgs> {}, withPyctr ? false }:

let
  pythonPackages = pkgs.python3Packages;
  pyfatfs = pythonPackages.callPackage ./nix/pyfatfs.nix {};
  pyctr = pythonPackages.callPackage ./package.nix { inherit pyfatfs; };
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
