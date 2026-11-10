"""Embedded artwork EN/KO phrase reference, generated from 2026-11-10 supplied workbook.

No Excel upload required. Source coordinates remain linked to original sheet/row.
Approved correction: D229 'Before rst use' -> 'Before first use'.
Other ambiguous text is unchanged, including alternate Korean translations.
"""
import base64
import bz2
import io
import json
from xml.sax.saxutils import escape
from zipfile import ZipFile

_B85 = (
    'LRx4!F+o`-Q&|FvBdP!quwVTofOCKU^FQzZ?mz$k@PB{*|Ns8~{+Iv|9$+G3q-@`AN4(KP(<WSS?Bm1cd)Ix^gE)G66cio1gH-h0VL?O{Hq<Iq0`e_WVy@$M'
    'k(i{_D`~Z>A-!*A3Zj}K2BEM@AclYlG$Yh#0Hy%dJkpQSY8z9?+LK~xdXH1Yo`?@n3?MWBG#UU6Pe?QbQ^+7DhDqfIqfwyRfCE9Mnhi7qKp6l400000BA(C+'
    'spOh8000004F-S!000000000000KfJBS4BzXv%p4nMblwjT2%3o}+4E9#OQ)2A-hNh+qIgpaGL1r=Ue9ieQqS$wp|@(?O%uG-%KO8Z-?600E#400E$A8U{vy'
    'Xe2}s5Ck+KpdbXFq|_NS(?9@d27mwow15Br&;V#?Bs@|4RloGB6W9FxCi;ENiS~)&mSgxdKQ+v(Z<0Ry`kr>zOWM^-qv`ZvYm?~v4c_T|qc?JRdp{g`F!#T5'
    'M~_`vkD9c{=!Sz0NHG{RQdYKHJ_h30$5(}>6*KJ8%nsF}debEdP0;*#E$6XK8mDd|AH=9h><vU9kCwfr()5<^#QfYKN*h!?+6~pRVEaf$-Pok`G0QwneI!zq'
    'JeqTl#jxjo9Ul8*<Y>*!vuimi>g9`Ablj1`;y-OTORXM2<nQNliJ-7??gq^;h<zU`13TTjY2!LI{s4nwGX={u<<-ojfv;$`;SC^nt`DLnw)U0$(Vs><d=BjL'
    '9HXyN`5HFjkGE$L0v_+^<>{Ol78I0v#Qu{gHhFj?O`B(8`l6l+OU-@C=gexZyDHq3B|Sph4`mFmXUshPeZGH(JiC@2Zu!vT&&Q9s$MN54V)TX`F3Xs2`Is@o'
    'kWwY;I2^{cEHnxf5JlvR_8XX&WLD<Qr4wd3W|qjKM{tLw!P|?@4Z=z%RN7Wz>;<FG$(C6MVV$i_j@g5DdPPXOanQdSbE5q?O{|V%4%GSjEC{yTf((v%-IX*$'
    '^z_DLn2>F$A|5j^I$6du3)v{It&DxETdz_z&BfH|%K9lY7PZqYf@adpDvoJ#-IXxw>|I`1zdor)3~v*CkP<R7n$Tk#zI?H?#*$^e>@aPZHH>E?X=*-$i0Fll'
    '8A3Pju~-BI;Ngpi)XsqlMY|;!A~A%ydql`(X@VXkG2hf(JYMdcgNQl;sjNabV#U45D}x$)MQY)hA&roZ!WIkzJ*z_yu49zIHBy1-FoqSA*_U5Rdg9d+O=sap'
    'AVd;3gB%-{Qf<q=BQ!=O=F9@>hPdSwc%X4A-UdpxDYc85kIe_w8H5p`^^XDiA^|OYBwldAwz=T}L~IubaWFLIuRb*p`i4%_BN+HMl66nNCJi3m9^(E%l+Oj0'
    'OPamk)_|vNiQ873$8;Rb?O(s%i{32edjAc?eZL5@R)sz03nDzP=R!YW4}F-B_@zs^Icv#bQWg^OR2Ol=fG?Dr1q_GikiIe09LJ!uDI?X)QKTd@b1rv^d2q>*'
    'fQdvswI4lNE<$3cIk`pg$c8L<Vd_nWLQ39$D5!6eX4kY`4zR-4IIW3I)ek}&5+knDsCVQ`$+IB~?gGV%r<GX2nqLBE>OJEsM<=?D@gjujGKn-v$|yoiQzB%x'
    'mo$x0CSg|xoMsXj+C&E4Ef_-kmq3W**tNi+b7-cCDjEuyoaq^BYlLZ}a^Fq5)|oL+Z<S417XwkVz3!xa%+mK~w|Xu`2g=O8G_8S^7^8_?!?Th>_^m-4>O_@w'
    'pjtmt`YA#{BY3*94M*tqqQYm!r`^50WqVOMk|^wa%4f4mZ)h97rJJcdiMv#_xvQ;1hKU80O4l@)l#FeMjK3o)bdwO1*er3(z6I*b50sk<BWH3f7!%5!f>N2{'
    ')WD;GkR>v1prLg$D6^|-n|)eywq}nI7u*na+B-{}&`Y6KBDG&8oR4<hag`302V!mcashYE!)U)bfW&7abH#j1Y>gslg@=ks3~sfujf+a^?A`_uY?P6q&Pxp8'
    'O-AU`&38m2@kDB3c3E8kx<O=BSd})6iuVpNn?W?DMg<l_TMK|==6=&HZbp{L7OZZHK<f3Efl4SuK@dYPYZ5<#yjsk903t2ax+qhy^M(Gq(Jwnt)gbDhVUqit'
    'U(?n}tVK^QeXGQG4Rm*4RjMTqYvr=lZ`s{&nsu3ZUfx!)!u?r%I%Alu)NEpK!tM~Guh9%w*)fwMmpzjX8?|&B^`RrS>&G={)O=NYrN1X4tFhMC7eqe=MR@Mf'
    '&5r`~+0_0s$@~^mUlsm?Gj`+lDjQh2noXf>V50@qPzKTkqr(Eb*-}VU(zbx~Y00}cy32D{ubbcYe{bWM=I=mPkeYez6p)qhj^^jh)NuHD<C8V7FKt9Gb@6uQ'
    'F_L6j7c8I}3-W2hp9_X$7l(<?M~}T0@t+{KrQBnKbyDjKm>OH=Pbs)aOo;DyjdryKF?@{>@`&0_Q=TSuZw=M1ZNZ}`83^7t%I0OHV7oBHTSl(DM~*}o;ZoRB'
    'oc6T6n08=SO4AtPL1ubAUawEqxzk?&5=ukeViG;JbZRh(ztQH!t6~KPBp7393nTyss2osx+dcCur>V+pYkLy-Y!5w*Z*WF1e(n!ZCHeID0j+y_&k(c4naKO%'
    'K{9GN3_g=1_b_TQsM>@Z*q0@!CaLu|sy(=H_&Bwz8@J=p%s4nX<dU<RJ$R!Vx>)Ev9>P6?Pd{T3-ND?BI}$YES8dC#B6#<A&qI0MC$-E^H?;N~J>@_QmCk6P'
    'gvrT7kaUT9LklX>C?PZmcxHGwLU5$*LKL1NRN(4K0Ha5xNT9@I7%elSvk5tHaMY*+tAeU{SA$_J(r)0^W+)rLX;m`_(?;siG;rroRVhgZ)mAAo*%a{^u@y$x'
    '&;(t)Duo~wNy_q2Lks8_z_x`)C{ri^z65fC9|=@mi4BUmqHhCwzg~|jY>z8DvZI2mnu0e0n%?GlXw3|+k_jB$IHZJH@*V+1Hm$5xK1%NM*?V`}93Y;0^`pnm'
    ')<i1n<qVj{M`QF;(doBsZEs7reeV^-#|UE^Z4I_DwlT$u9Mw>6KYgByKd4{Ah9<P#!fCFz!j1Uhml83(V%Tz8tgZ2qG!j#N3f8PcaKuDHM9j*Ria?VyDpHhE'
    'S(#E<nHEH}I;GOM#73309P?+aZj7MkP*h5G4g?Sg0j)<l0}8kyxWrVH#Y(EEsZK%0=G({_!8Qd1QSg!#ob3Trv|^Ha#LA4IZK{O<L?{sfLWqS5ASp*!vf{@T'
    'Th%K9ZWgQEYukK^y<HsjHyb$W+$8SRSD#X(gKT4lIZWt#aj@4d`<rJr=$Kz6dMdtR&v+;ZB$5aqlU5nk76P-P!Rq=tqD>K%Dhh%~B$7!agVUnT)D9~uPOven'
    'jNq{`nIw`)B$5drILyHzH4&Vp2`nbDlV-Cdl0hUAK_my4m&wzd4COUfMawzPO=%>ONhE>@HUnSpLEYv+Hjf8cTg5&I2g!zn2Kz<x;&w;3LLnsPN)!!J^Kv{Q'
    'P5gGLtmfao<ecWs;o;OO=j&ro_MGN;t93%bQc5##eduR_U)pEP`ZCTdacwSVx=-6&s7V$WVPkI22Jvt{#2Fp5)h10B$ZbTQt#r9{c9pigOoIXFR4Hg1D8Q6g'
    '1vQ}u+j?kA)X`YQ^JHYvxALv4zDUYK@W?4C9J%}+v!%NG3-iKDE%zv?LYNUFmqMWE%1U)6G(iau!0mNJz)+xij|fs~)moz{bDUgw(Vj8Gn|H`HC}Dv-Y#a@U'
    'p<>h8bt4``3WI%`<HRaRVswX8I5WW%?8^f}u!7xV5{48x4FW;#AqA@B)dXYq)XE7~sOaIsrG{`KtzUXpWQ{I24ki}1+U8))Yf{YT5hRds$5NnWVl<O~TGYaI'
    ')tMWGzt&a~se`Quv0A7bM^PRk=VwL3nm3hZ!gLqOXO#`*(QF5_tkLcXB&;V>hIXpB@4pURwOJi81;SB*qZ^H_w$)J^rvlst!WMS)C<4O}J4yu$RtD4&d@DEs'
    '#bB}uSE$_}axW~_!$WF;C7R#P0MZr<wC(IRJjl?%T*b^-Q19hz%MgxsUDE}Iagh)+qk)eqRgC&g;rTs+p>U#^AlY>c@5teTWv-46-LDen4h&-~T{+_J7Hh7U'
    '^um+ca#pMvkG7R%t%gaoVWb_`ish*b3(6bywFY5Y;zg3dg`qMjb%kSG@n;pyqFO-4lWjCMk(pQCtl;8f`IN|d*-J168s=psQzRvkkyEydNwHvp(z4Kn1xtbF'
    '7E);(Zc|fC0iQXD&#hmm<;>fj^IVNNL|)h2SFfxmRYYmM5}4VSk1`b55%qp=bIXhb74SiT9PQ1ToG*J*LuUePH%7*OAd(a&D4j$oo!<YK%=!;|F3z)0ADY?R'
    '(zs#VHxuB_j=_adE-wcY_X!&PctDgz-2N-|eLS-sKG)5Dz2ZGSm!-PKpv3a@bPee3NH>W@u#}(`5K#2cUz^IE25Xlq8DLfjGBL?pOH`2Na|<_&Qm`Q#j7}_k'
    'staohV-P^SmW4phn@eO0RZ)s4Y4kJU@uM1O{lYF`Zq<GEXsnF-Q&iwHOAm>k9P%+|eLE`{p3-_f+)}IMnIX`jL#Ve^Gr+a`&^1^@8QbEGxP~08@z&y9KL}ln'
    'hS@Fdbr?`FqNP4#Mi##aW{s6Hq>r~{*3?Y$Z!nuf=K8qxWP?Y{)QlN`(*}~{9Lft+XAs85G+I%e=Sq->bMl4VRHZ4zG369PV<?wUX*Sz!xJW}z@?F6xj5^99'
    '#X{U@TxIdbRjwGe(pb{gx)`d?HOEr@+T?RQ2<PNH+cc7yMqCQWKWVUTGnAiTuVX?!NH^uuA@Cr<+U3+HO;~4I$)!m2#4BaHX<Do7khyKGxhuWlAmSC_vK$vT'
    'L@k?wC%qTpW^31WZy+$oYCa}IMIgn_luVh#`;dkwGsQ!jgaGXw9{G4tdr_yE(ZM2zLq*Mo1#6cW?9`KtLQC0xSk)>_a2&@q9gu4!2&`>3E&9f}@1{dXuJ~Km'
    'rk7Wi#x;&zk@=B!u+n_dZ6k5JWhhb2VYsSVN=9c@4Esp$$C2#!8<@*-=hFx!?A@_-E8w@AgdW`me%~@h`6IYi>r_T=g7G6l%B?SPqPAO!2x{*P1hX1!OVLze'
    'A#X!iPqeY3C7>DK!67lF*8$XalS0QPkX0b-VA~jK={*~g#>dx?q0NYM=~pKDC)?Y!*Bg^aI;=oQyh9gf&46r3Es2bnM)|PM3|%XHtP!Sk?y=2}#J#)`g>lsO'
    '<?`|jUF}<j1nkKipHe(9dQB{Js+La&8?emqIuMf8G;_fQt!*?2HF<QVX3WsrM&;_)I#WcfZ_Vvfun<z!DI^aKJvw7+?zch%77#Fd0<Tc8EHbOK)>FWxMBw1Y'
    '(_@|bik(#FG4GEW^Rd#NPONp(A76~>&hm*(whfOQr6YnxH*L&T09cG#-Z)_xT|?dSp>P>k2VKm}@YP!8DSYV+HMa;0Y(85Zi-Vy>8gd#TgAI^ZY%;uKGb$`F'
    'Zwd-#P>Q4bQ!=p(SqSWuQ6*A=LX^s+ey^p1JYl3_v!Nl=8BJ4k1+)^4ntOP2U<@-hja!gJiV4xMphF<GPAtOh>Tj?EMWaz>nX4>jjU!q_43>bd0=yVaq0(}q'
    'q-b`j5|&~(Bh{e?i47W_K1lMLy6hY`Wbp#Rh8_>E+*r>DHw3)w%-Y|t=@5^xg^oQ}auc$H-|de}P@1w<I9!BMo`Wo;Y!&v^8XHJsZxOc{$t?5lEl01z>8)2A'
    'K+a+^>rg{zXfDvU3>duQK6Gnp><mM4T&7H|E;7Ld5?_N%4BKrBTzGaCniWXeBS}Wan`~{3?TMXbU8Q$M>k!U^Xk%XB!X2E;h&tL!3~w@BnWeTsgByxMIg^dH'
    'H%+mOYMI<c$OG5nz$}hPb+W@*#;Su&jA_KlfrWR%EnMkK`MJuw_lBD_cO5lBi#;CiyEd6@vMBYC)Y(=HD{~+v_$m;vvqPHZIVhnjPn^4HryZTP4i_*giq}rQ'
    'xR-=zDYZpMHtM!aSWvPIyDA!X+J;d%BfVPM%FuZRI-y1f&JbeJr?7tAVFeA_V>}kg7C#(ChV3M<v!RMs6Mckqm4bU22a+CC*&9X@$Qo&d3|%7&O%0HfR)ac&'
    'Mw)DiQ#y9srt*?Y4Hc#}6k<CkH!jBzS<|YLHX_W&3e`g5nQ4t7bd289y^IpuY-1x!CKftU!p&fcRCtvzy-CA7R3eEV4QcW-t2;3#iy|wDvtU?gZH;0eBtmCm'
    'u4XqyYZMKQ8alOAdf=59V}m{Tz-6tDXt`0g@yXJ1-R92Py$Ys@G*Bl7R)qcA9wdJZTo#?^F|8SzJrHp*<@HH;wi~lHE*oG**9L8(d;UpUu(C!FZxpi}XnMlA'
    '_qRixNC{;M&a*ZsV-C<Y>`#?jvCFGjjJptzAmIUoMTWNxY`*<BOx<$f1>n~kVv*U6=5HYKsPslm2Rr{fN8bN`@&q3`zEu$vu;{fVhvA|pZpNdljuAn@`!n6T'
    'h1I3u{f!EW;l{_z{7Yh=u#_xXjWKc#6HAh(&6<h9N>I;a!G`3q{+yM01@EcBE(lXuqu0?O(V+av2x&Hn1__~zf&}9i5gg;~v@{>z>nJbv`o+>Qk0y&PsTdsf'
    'Az9~mvAiSLF70e+Q>Y+~=HOez(glqXswQBV;lU<cO#<gGh+UzzhV$cg4RHnoI3ky8OUg7Vvf?hgwHIm;(Ifp+M=_kz=8}=LSQbL5A_TQ4@sRy~m?H(GL~Kl('
    'mtg`m%3ETnEtoG8L<IzP4J!;yj0p{4pf<W{f7kKDAU67wq^u|!Xo8efB7nPWSP!7E1%X%=0f8V0NK(KAUE`UI;+K7quxzFlBMl&6gu1*cTgkbtR5X8|Xk8aY'
    'Gdlm?p=Kq~VZdmSBRqv0s4(0Ck<v}zw}DVf1P5~9F&r$}3eu#L>4Q5-z!&(M|8>1di_f$<u#|5b)p0EpByNm9D7kp!m&($#GzBzrInZqE;xvO$!zPRaCfJc;'
    '%K-t7hqgc^9@g*c^r#I#6ckRHBv6ACVvF&pTiB8`NzqaJRFW`3+{_i@^30DyK@fNQyxA@gy-bKJQ*S^d0BIOXD3J&ZLWn>Gx#ZO{OSG17vwB{sg9?F21>&2o'
    'b{Cr>XH5o9M-{NnYS7HU8HC+ZNwGG9xm28TSQjByydlnxULA!2xIk`z*4S_!0K6RJAX+iBBuVsbVub)`{{x;0Uo9Q+_cn`bNuU~1<sAGOs;Q+wApkbfbSg^A'
    '$JXACFY*jHux(2U(kgqy2_=IYeeuPrGVr6DOlB8{RLaR#O9@nwtU^vowss2@D|k~Fz*A61Q6NIZ>eyT`b`r&C#_3g#j7;W%(UEouYl8y7V?=LFa4z26V<$3Y'
    'vp@>2yh2|Fd>UvG7f8ZFLlFp>n&=3LVaqUp=o$qR0AU!22wqhEM039sQ8dn<Yqo0Tr?3Fgg9ac>CHveR@MIeim((e1c*05X_hKWKX#t`_C$rzu1dG*J7?R!7'
    'esGe<qoKx-m$1f$+Z!-QHdawls-(bRP-Pfnf$NF5kPHSKhHOnIQ6|w%P?|S@5kZ5^wngDvkgy0tNg;?B#xQI)qjA<AX-pU(r(k_fX>quJ>P$W(raV2;1%mVT'
    '`B0m|h}Z~rK-LB^rVMPrb}}kSrDIiqJE3Oej{-bM|IF3c+qfvE(NhD<Ml8DKsqV>|1vV(T)Jwm}FvSarR%pFfErqgxoM;lTfinO%o2a(S!O$^PrkA0ql~4g8'
    'wJu&QGpUiFURSAIl({yc2`QC}>rt4uK)jVx0ik#x5Ez;oLs6vKN(n^5MGz;9#1A0&J199%KZTqgh%vr}*rZ2wCT$lergB;Z#==F=4k^3Ubc)C`14Byy5GxSE'
    'AtxkaX$>GuNrM1sE&6%ev>}8+^^cEKN;VMWly8})>)LAggNrB$e)d;Lvykd0sZgFl)-Xe%(6ZRQbCjkqP~2vpO$cO}41g@v1X7YvBpG}}P{lN`_@Fqn92^ZV'
    'GYj&*@ZN;bDhI*uTIX1T$$-{tG!6lh{FxA8<f2I#()(wjdlL&FW|n9a>XIi1B_RdK+&r>xgDggvC4!sEi8Qr6q>Fcjkqr>4JQ4|U@lfnIZ{Q@8OJYPM)1N1b'
    '`WCnVGvMLH?ITp=X)%hFoi!CpldKDunl-1{4|2AdF;qu>gi8>?g$P`wM_?!oK3o)F!5+mCZTnkZt?QKO72YQ9t6ZS6Yx!T-bIP1Qi}W9F+3{;`{w~^Z9l^ub'
    'p2wXG7X9rMF@|^;?ab*)8vOHfo;aU}7i!n+tznPjy`I*$+{#V<U&WaI(f-an`T~Y?VOw;-=w$!lpMFuYy@Fb3g`>L<lzjS@o8YngCsW?<kDpA|U606ue1auF'
    '+3=h8N7;M~s$HAbA;BK9B`(V)^);f9hTq-}A9o~Y^I&JM2?{<P*bJe{LgPnt!bV|8AwS<X?MWp@n)0ncp=l6Mqe^z<8{)<F>Vp=dWK`a&)&we8*0N698)Tk?'
    'ZZ|{)A%jSF)!?Ybu{*sN_ae%!1SeCh<tD)G1MCLIfu@%19_W3;2K^Mo#24l8;F#+kQg^<=_Xx%jWHCb+p-UMe5iOJ`wK32gwQbnmhKiZZLLIthDPjbX*%v<Q'
    '0+OBG*_@bjw5xd!HQ!kgKZ9l)8=}#pUPCZ9>p+9XLPQ8Qm^^Yv4PbAE@hhLC?<QN1P(n`vEd-cHGqD((f-BOKzb&UA(N!31z4R-ppcJj6WN9ZliU+@C#e#%v'
    'aWKK@S^-33bA?2(ts1t8O3O=zZEQvHG)3?#XgwC^22c=eHl%ZuyQ)CP@1`wNL1cUFK+2f%Ak)ciCBmeMZA?P#H`FnpzM1CqdEPM4$!r#(T9&CaFCcA@ZLx9='
    'o+!B?)P{<joD}T=;(%l1Fl-RY1S0K1$npo=3Q0!J$dc=I-;mlFt-DqSv0Ey7lFk1mwi1Er9H%yn4bihc1jV2YkHHaXDARnH5Wp_8JZw^LAX6wB=EjpvF-j&1'
    'DPdaH5W@zRJ{R02;fZUOgs2ZTn>{fRx<=rxWGhK|OkJkYtcQAg&d~$Hk(BF0(}s(D=G52El!`>QbpvlVT6Z$cA6z06Z-dkhjL4Q$fsHma#<s2pVqVp2NU(>U'
    '7>PcLCy@;I9h`jZP&W*?s9|+b#8tnmcBrzV5@Z&6Q#7SKQXvJ}X|j1MY^6nHGpRJB7!QaPM{9uc?<pq&u!hCwO)epxUJ!1ndC`u?17W=}?yGNM-KWH{5u-Z2'
    'rHLu^83)70QRGItEt70-(55p!DPJcwy7AAY!fd$@-w@5UA0nFCSUHt%JgI2nFH6P=ri3Ot&@w-8c@-Nf^%n)$Q%TUx2IFk0VL7=Ffz{lBWm>&yT`hw_i$47M'
    'Oxt8@A&8_~6iSs?jSjFV5PGvCAu3$J?>$Jp&3%yB-HI#T+v3nK{stb(I9#2gM~p-!dj|mYP~63S2b>$Cp+S%hvw6shkEr%XY1oSfvW(hAS@1F%P3Deh=O=hE'
    'RDgsYL^I@c+~rtpwAM{;WU;d1U=kybpCmB)5KNJ|6)ZH-y(YuPX-Xr;_;5IFC>bT><>IC<!ttw#hWMN<_bZtuaGGb9bAqBIh?IfJG9@#3bQ%QJ?}N7J>4g!1'
    ';sm2tfX2vhE@;PXxUFLp!h%H~aM-ont&Jge2^)fCxIxiDpfKAxIpfK-1sm4Nz5H*V0o|;Et7YeSTjCjMwv*#fT?1ocO@k4@I!5Hc&}Bl_LY`phHa0ZZc*;=0'
    'F?V)r!}Rb6jOdf1HEJ`?gcvd?qMkmyLm_zRQ=)5<E#-QoxL7^W7AbFo9JY~it4P}L-M(4GO!bg~cS>W9)L)`B4+F`2>zdkdsS=E5#a!*ziR-PEFXC%ai@yOw'
    'e(6vD7ji{7P>=$OBdP'
)

def rows():
    """Return [source_row, TYPE, condition, EN, KO, Remark] rows."""
    return json.loads(bz2.decompress(base64.b85decode(_B85)).decode('utf-8'))


def embedded_reference_workbook():
    """Generate a minimal in-memory xlsx understood by the current excel_loader.

    Never writes a file or changes the approved source workbook.
    """
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    def cell(ref,value):
        return '<c r="'+ref+'" t="inlineStr"><is><t xml:space="preserve">'+escape(value)+'</t></is></c>'
    content=[]
    for row_no,*values in rows():
        cells=''.join(cell(chr(ord('B')+i)+str(row_no),val) for i,val in enumerate(values) if val)
        content.append('<row r="'+str(row_no)+'">'+cells+'</row>')
    worksheet='<worksheet xmlns="'+ns+'"><sheetData>'+''.join(content)+'</sheetData></worksheet>'
    workbook='<workbook xmlns="'+ns+'" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="텍스트 대조 데이터" sheetId="1" r:id="rId1"/></sheets></workbook>'
    relationships='<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/></Relationships>'
    memory=io.BytesIO()
    with ZipFile(memory,'w') as archive:
        archive.writestr('xl/workbook.xml',workbook)
        archive.writestr('xl/_rels/workbook.xml.rels',relationships)
        archive.writestr('xl/worksheets/sheet1.xml',worksheet)
    return memory.getvalue()


def load_master():
    from excel_loader import parse_reference_excel
    return parse_reference_excel(embedded_reference_workbook())