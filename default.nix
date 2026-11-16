{
  pkgs ? import <nixpkgs> { },
}:

rec {
  pyctr = pkgs.python313Packages.callPackage ./package.nix { };
  # mainly useful for things like pycharm
  python-environment = pkgs.python313Packages.python.buildEnv.override {
    extraLibs = pyctr.propagatedBuildInputs ++ (with pkgs.python313Packages; [ pytest pip build ]);
    ignoreCollisions = true;
  };
  pyvenv = pkgs.stdenvNoCC.mkDerivation {
    name = "pyvenv";

    dontUnpack = true;

    installPhase = ''
      ${python-environment}/bin/python3 -m venv --system-site-packages $out
    '';
  };
  tester = pkgs.writeShellScriptBin "pyctr-tester" ''
    PYTHONPATH=$PWD:$PYTHONPATH ${python-environment}/bin/pytest ./tests
  '';
}
