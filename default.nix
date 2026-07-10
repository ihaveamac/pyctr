{
  pkgs ? import <nixpkgs> { },
}:

rec {
  pyctr = pkgs.python313Packages.callPackage ./package.nix { };
  # mainly useful for things like pycharm
  python-environment = pkgs.python313Packages.python.buildEnv.override {
    extraLibs = pyctr.propagatedBuildInputs ++ (with pkgs.python313Packages; [ pytest pip ]);
    ignoreCollisions = true;
  };
  tester = pkgs.writeShellScriptBin "pyctr-tester" ''
    PYTHONPATH=$PWD:$PYTHONPATH ${python-environment}/bin/pytest ./tests
  '';
}
