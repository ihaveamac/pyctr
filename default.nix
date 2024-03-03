{ pkgs ? import <nixpkgs> {} }:

{
  pyctr = pkgs.python3Packages.callPackage ./pyctr.nix { };
}
