{ pkgs ? import <nixpkgs> {} }:

rec {
  pyfatfs = pkgs.python3Packages.callPackage ./pyfatfs.nix { };
  pyctr = pkgs.python3Packages.callPackage ./pyctr.nix { pyfatfs = pyfatfs; };
}
