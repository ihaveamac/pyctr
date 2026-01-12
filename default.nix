{
  pkgs ? import <nixpkgs> { },
}:

rec {
  pyfatfs = pkgs.python3Packages.callPackage ./nix/pyfatfs.nix { };
  pyctr = pkgs.python3Packages.callPackage ./package.nix { pyfatfs = pyfatfs; };
  # mainly useful for things like pycharm
  python-environment = pkgs.python3Packages.python.buildEnv.override {
    extraLibs = pyctr.propagatedBuildInputs ++ (with pkgs.python3Packages; [ pytest ]);
    ignoreCollisions = true;
  };
  tester = pkgs.writeShellScriptBin "pyctr-tester" ''
    PYTHONPATH=$PWD:$PYTHONPATH ${python-environment}/bin/pytest ./tests
  '';
}
