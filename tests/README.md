## Testing file sources

### romfs.bin
```bash
3dstool -cvtf romfs romfs.bin --romfs-dir romfs-test-dir
```

### icon.bin
```bash
bannertool makesmdh -i 48x48.png -o icon.bin \
    -js "japanese short title" -jl "japanese long description" -jp "j publisher" \
    -es "english short title" -el "english long description" -ep "e publisher" \
    -fs "french short title" -fl "french long description" -fp "f publisher" \
    -gs "german short title" -gl "german long description" -gp "g publisher" \
    -is "italian short title" -il "italian long description" -ip "i publisher" \
    -ss "spanish short title" -sl "spanish long description" -sp "s publisher" \
    -scs "simplifiedchinese short title" -scl "simplifiedchinese long description" -scp "sc publisher" \
    -ks "korean short title" -kl "korean long description" -kp "k publisher" \
    -ds "dutch short title" -dl "dutch long description" -dp "d publisher" \
    -ps "portuguese short title" -pl "portuguese long description" -pp "p publisher" \
    -rs "russian short title" -rl "russian long description" -rp "r publisher" \
    -tcs "traditionalchinese short title" -tcl "traditionalchinese long description" -tcp "tc publisher" \
    -f visible,autoboot,allow3d,savedata,new3ds -r northamerica,japan,china -ev 1.2 \
    -cer 10 -er 20 -ur 30 -pgr 40 -ppr 50 -pbr 60 -cr 70 -gr 80 -cgr 90
```
