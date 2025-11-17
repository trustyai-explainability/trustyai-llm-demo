#   Troubleshooting

### ConnectionError when running [`../common/prompt.py`](../common/prompt.py)
Ensure you have port-forwarding enabled in the background by running the following in another terminal tab.
```sh
oc port-forward $(oc get pods -o name | grep phi3) 8080:8080
```

### Pod unschedulable due to insufficient CPU
The model pod does not start, and you get the following error:

**Pod unschedulable**: 0/3 nodes are available: 2 Insufficient cpu, 2 Insufficient nvidia.com/gpu. preemption: 0/3 nodes are available: 3 No preemption victims found for incoming pod.

This is a common occurrence when resuming a cluster from hibernation. The issue is that the system pods gets started on the GPU nodes' CPUs, so there are no available CPUs on that node. The simplest (nuclear) solution is to delete and recreate the Data Science Cluster `default-dsc` by running the following:
```sh
oc project redhat-ods-applications
oc get datasciencecluster default-dsc -o yaml > default-dsc-backup.yaml
oc delete datasciencecluster default-dsc
oc apply -f default-dsc-backup.yaml
```
Alternatively, go to Operators > Installed Operators > Red Hat OpenShift AI / Open Data Hub Operator > Data Science Cluster in the OpenShift Console to delete and recreate the Data Science Cluster `default-dsc`.

The required pods should now be able to run. Go to Workloads > Pods in the OpenShift Console to verify.

Note that for some demos, you will need to patch it to allow code execution and online evaluation.
```sh
oc patch datasciencecluster default-dsc \
    -n redhat-ods-applications \
    --type merge \
    -p '{"spec":{"components":{"trustyai":{"eval":{"lmeval":{"permitCodeExecution":"allow","permitOnline":"allow"}}}}}}'
```
