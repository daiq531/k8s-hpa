# !/bin/bash
pod_name=$1
num=$2

for (( i=1; i<=$num; i=i+1 ))
do
    rslt=`kubectl top pod | grep $pod_name`
    echo `date +%Y-%m-%d` `date +%H:%M:%S:` $rslt
    sleep 15
done