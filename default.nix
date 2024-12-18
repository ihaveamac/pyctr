{ pkgs ? import <nixpkgs> {} }:

rec {
  pyfatfs = pkgs.python3Packages.callPackage ./nix/pyfatfs.nix { };
  pyctr = pkgs.python3Packages.callPackage ./package.nix { pyfatfs = pyfatfs; };
}
