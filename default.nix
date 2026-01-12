{
  pkgs ? import <nixpkgs> { },
}:

rec {
  pyctr = pkgs.python3Packages.callPackage ./package.nix { };
  # mainly useful for things like pycharm
  python-environment = pkgs.python3Packages.python.buildEnv.override {
    extraLibs = pyctr.propagatedBuildInputs ++ (with pkgs.python3Packages; [ pytest pip ]);
    ignoreCollisions = true;
  };
  tester = pkgs.writeShellScriptBin "pyctr-tester" ''
    PYTHONPATH=$PWD:$PYTHONPATH ${python-environment}/bin/pytest ./tests
  '';
}
