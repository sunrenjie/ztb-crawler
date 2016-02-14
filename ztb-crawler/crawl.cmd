@echo off
:home
crawl.py ztb1
sender.vbs ztb1
set t1=%random:~0,3%
set t2=%random:~0,3%
set t3=%random:~0,3%
set t4=%random:~0,3%
set t5=%random:~0,3%
set t6=%random:~0,3%
set /a t0=%t1%+%t2%+%t3%+%t4%+%t5%+%t6%
echo Will sleep for %t0% seconds before the next try ...
sleep %t0%
goto home

