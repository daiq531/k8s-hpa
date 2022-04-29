#
# Copyright (c) 2020 by Spirent Communications Plc.
# All Rights Reserved.
#
# This software is confidential and proprietary to Spirent Communications Inc.
# No part of this software may be reproduced, transmitted, disclosed or used
# in violation of the Software License Agreement without the expressed
# written consent of Spirent Communications Inc.
#
#

import math
import time
import json
from logging import Logger
from threading import Thread, Event, Timer
import requests
from kubernetes.client import AutoscalingV1Api, AutoscalingV2beta2Api

from cloudsure.tpkg_core.tcase.error import (TestFailure, TestInputError,
                                             TestRunError)
from cloudsure.tpkg_core.user_script.kind.helm.types.k8s_client_v1 import \
    K8sClientV1
from cloudsure.tpkg_core.user_script.types.iq_results_v1 import IqResultsV1
from cloudsure.tpkg_core.user_script.types.ssh_v1 import SshV1
from cloudsure.tpkg_core.user_script.types.user_script_v1 import UserScriptV1

from cloudsure.providers.nfv.k8s.client_initializer import ClientInitializer


class PodCPUAdjuster(Thread):

    CALC_COUNT_BASE = 1000
    WAIT_METRIC_STABLE_SECS = 20
    DIRECTION_INCREASE = 1
    DIRECTION_DECREASE = 2

    def __init__(self, platform_svc_ip, api_client, namespace, pod_name, pod_ip, target_cpu, tolerance, log=None, iq=None):
        super().__init__()
        self.platform_svc_ip = platform_svc_ip
        self.namespace = namespace
        self.pod_name = pod_name
        self.pod_ip = pod_ip
        self.target_cpu = target_cpu
        self.tolerance = tolerance
        self.api_client = api_client

        self.log = log
        self.iq = iq
        self.run_flag = True
        self.stable_flag = False

        self.current_count = 0
        self.previous_direction = self.DIRECTION_INCREASE

    def get_pod_cpu_metric(self):
        resource_path = '/apis/metrics.k8s.io/v1beta1/namespaces/' + \
            self.namespace + '/pods/' + self.pod_name
        try:
            resp = self.api_client.call_api(resource_path, 'GET', auth_settings=['BearerToken'],
                                            response_type='json', _preload_content=False)
        except Exception as e:
            # ignore 404 exception
            # self.iq.write("Exception", str(e))
            return -1

        data = json.loads(resp[0].data.decode('utf-8'))
        cpu_metric_str = data["containers"][0]["usage"]["cpu"]
        if cpu_metric_str:
            return int(cpu_metric_str.rstrip('m'))
        else:
            return -1

    def adjust_load(self):
        url = "http://" + self.platform_svc_ip + \
            "/redirect/" + self.pod_ip + ":8080/start"
        payload = {
            "count": self.current_count,
            "interval": 0.01
        }
        resp = requests.post(url, json=payload)
        # assert resp.status_code == 200
        self.iq.write("set count for {} complete!".format(self.pod_ip), str(payload))

    def run(self):
        while self.run_flag:
            # query current metric
            cpu = self.get_pod_cpu_metric()
            if cpu == -1:
                time.sleep(self.WAIT_METRIC_STABLE_SECS)
                continue

            flap_count = 0
            if cpu < self.target_cpu:
                if self.previous_direction == self.DIRECTION_INCREASE:
                    self.current_count += self.CALC_COUNT_BASE
                else:
                    flap_count += 1
                    self.current_count += int(self.CALC_COUNT_BASE /
                                              (2 * flap_count))
                self.adjust_load()
            elif cpu > self.target_cpu + self.tolerance:
                if self.previous_direction == self.DIRECTION_DECREASE:
                    self.current_count -= self.CALC_COUNT_BASE
                else:
                    flap_count += 1
                    self.current_count -= int(self.CALC_COUNT_BASE /
                                              (2 * flap_count))
                self.adjust_load()
            else:
                self.stable_flag = True
                # self.iq.write("Pod {} cpu load and metric".format(self.pod_ip),
                #              "current_metric: {}, calc_count: {}, target_metric: {}, tolerance :{}".format(cpu, self.current_count, self.target_cpu, self.tolerance))

            time.sleep(self.WAIT_METRIC_STABLE_SECS)

    def stop(self):
        self.run_flag = False


class UserScript(UserScriptV1):
    """User Script class.

    This script expects to work with corespondent helm chart package. Once the chart package is deployed on the 
    target cluster, this user script will be executed. To identify the resources instantiated with the chart,
    one value with name of name is mandatory in the values.yaml file, and other resources name are defined based
    this name, such as hpa resource name will be verizon-hpa if name value is verizon. This name is also
    needed to be define in this script input arguments with same value.

    The following arguments should be specified in the user script arguments::

        (str) k8s_namespace: The Kubernetes namespace to be used for the test. The user-script will look for
            all Kubernetes resources within this namespace. By default, the value is set to "default".
        (str) platform_svc_ip: the ip address of pre created platform service. the rest API to http client will be 
            sent to this proxy then forwarded to http client pod.
        (str) clientName: identify prefix of client resources deployed from chart file, must be configured with same value
            of clientName key in values.yaml, used to qurey deployed client resources in cluster.
        (str) serverName: identify prefix of server resources deployed from chart file, must be configured with same value
            of serverName key in values.yaml, used to qurey deployed server resources in cluster.
        (list) cpu_util_list: the target cpu utilization of HPA
        (int) cpu_tolerance: cpu load will be generated to range [request*cpu_util, request*cpu_util+tolerance]
        (int) watch_timeout: timeout seconds value of each watching for utilization and load rate combination
        (int) scale_query_interval: the interval senconds of querying current scaling status
        (str) autoscaling_version: must be align with HPA version used in Helm chart
    """

    def __init__(self, log: Logger, ssh: SshV1, k8s_client: K8sClientV1, iq_res: IqResultsV1) -> None:
        """Constructor.

        :param log: The logger to be used by the class. Log messages sent through this logger will be
            incorporated into the test-case diagnostic logs.
        :param ssh: An SSH utility used to create SSH connections for the purpose of executing tools
            on a remote instance.
        :param k8s_client: A object used to access kubernetes resources. The object will have been
            authenticated with the kubernetes system based on the test case authentication configuration.
        :param iq_res: A TestCenter IQ utility object. This object provides access to the TestCenter IQ
            persistence. As of this writing, a label/value result-set is available to record data collected
            from the script.
        """
        super().__init__(log)
        self.log = log
        self._ssh = ssh
        self._k8s_client = k8s_client
        self._iq = iq_res.label_value_writer

        # construct related api object which will be used
        self.api_client = k8s_client.v1_core_api.api_client
        self.core_v1_api = k8s_client.v1_core_api
        self.apps_v1_api = k8s_client.v1_app_api

        self.pods_dict = {}

    def update_target_cpu_util_in_hpa(self, cpu_util):
        '''
        Update target cpu utilization in hpa.
        One possible exeption happen, see: https://github.com/kubernetes-client/python/issues/1098
        '''
        if self.user_args["autoscaling_version"] == "v1":
            body = {
                "spec": {
                    "targetCPUUtilizationPercentage": cpu_util
                }
            }
        elif self.user_args["autoscaling_version"] == "v2beta2":
            body = {
                "spec": {
                    "metrics": [
                        {
                            "type": "Resource",
                            "resource": {
                                "name": "cpu",
                                "target": {
                                    "type": "Utilization",
                                    "averageUtilization": cpu_util
                                }
                            }
                        }
                    ]
                }
            }
        else:
            raise TestRunError(
                "unsupported HPA version {}".format(autoscaler.api_version))

        try:
            autoscaler = self.autoscaling_api.patch_namespaced_horizontal_pod_autoscaler(
                self.hpa_name,
                self.user_args["k8s_namespace"],
                body)
        except ValueError as e:
            if str(e) == 'Invalid value for `conditions`, must not be `None`':
                self._log.info('Skipping invalid \'conditions\' value...')
        except Exception as e:
            self._log.error("update hpa error: %s" % str(e))
            raise TestRunError("update target cpu util %d fail!" % cpu_util)

        self._log.info("update target cpu util %d complete!" % cpu_util)

        return

    def get_deployment_metrics(self) -> dict:
        '''
        Get metrics of pods in deployment.
        See: https://github.com/kubernetes-client/python/issues/1247

        return:
        {
            "pod_name": {
                "cpu": 100m,
                "memory": 1000KiB
            }
        }
        '''
        resource_path = '/apis/metrics.k8s.io/v1beta1/namespaces/' + \
            self.user_args["k8s_namespace"] + '/pods/'
        # response value is a tuple (urllib3.response.HTTPResponse, status_code, HTTPHeaderDict)
        resp = self.api_client.call_api(resource_path, 'GET', auth_settings=['BearerToken'],
                                        response_type='json', _preload_content=False)
        # transfer resp body to python dict like below:
        # {'kind': 'PodMetricsList', 'apiVersion': 'metrics.k8s.io/v1beta1', 'metadata': {'selfLink': '/apis/metrics.k8s.io/v1beta1/namespaces/qdai/pods/'}, 'items': [{'metadata': {'name': 'busybox', 'namespace': 'qdai', 'selfLink': '/apis/metrics.k8s.io/v1beta1/namespaces/qdai/pods/busybox', 'creationTimestamp': '2022-03-12T03:00:05Z'}, 'timestamp': '2022-03-12T03:00:05Z', 'window': '5m0s', 'containers': [{'name': 'busybox', 'usage': {'cpu': '0', 'memory': '1076Ki'}}]}, {'metadata': {'name': 'client-pod', 'namespace': 'qdai', 'selfLink': '/apis/metrics.k8s.io/v1beta1/namespaces/qdai/pods/client-pod', 'creationTimestamp': '2022-03-12T03:00:05Z'}, 'timestamp': '2022-03-12T03:00:05Z', 'window': '5m0s', 'containers': [{'name': 'http-client', 'usage': {'cpu': '5m', 'memory': '51388Ki'}}]}, {'metadata': {'name': 'server-deployment-55699d7b-xgvb5', 'namespace': 'qdai', 'selfLink': '/apis/metrics.k8s.io/v1beta1/namespaces/qdai/pods/server-deployment-55699d7b-xgvb5', 'creationTimestamp': '2022-03-12T03:00:05Z'}, 'timestamp': '2022-03-12T03:00:05Z', 'window': '5m0s', 'containers': [{'name': 'autoscale', 'usage': {'cpu': '4m', 'memory': '48836Ki'}}]}, {'metadata': {'name': 'ubuntu', 'namespace': 'qdai', 'selfLink': '/apis/metrics.k8s.io/v1beta1/namespaces/qdai/pods/ubuntu', 'creationTimestamp': '2022-03-12T03:00:05Z'}, 'timestamp': '2022-03-12T03:00:05Z', 'window': '5m0s', 'containers': [{'name': 'ubuntu', 'usage': {'cpu': '0', 'memory': '99776Ki'}}]}]}
        data = json.loads(resp[0].data.decode('utf-8'))
        self._log.debug("metrics data: {}".format(str(data)))
        metrics = {}
        for item in data["items"]:
            if item["metadata"]["name"].startswith(self.deployment_name):
                metrics[item["metadata"]["name"]] = {
                    "cpu": item["containers"][0]["usage"]["cpu"],
                    "memory": item["containers"][0]["usage"]["memory"]
                }
        return metrics

    def get_hpa_status(self, hpa_name):
        autoscaler = self.autoscaling_api.read_namespaced_horizontal_pod_autoscaler_status(
            hpa_name, self.user_args["k8s_namespace"])
        hpa_status = {
            "hpa_name": hpa_name,
            "hpa_version": autoscaler.api_version,
            "max_replicas": autoscaler.max_replicas,
            "current_replicas": autoscaler.status.current_replicas,
            "desired_replicas": autoscaler.status.desired_replicas
        }
        if autoscaler.api_version == "autoscaling/v1":
            hpa_status["current_cpu_utilization_percentage"] = autoscaler.status.current_cpu_utilization_percentage
        elif autoscaler.api_version == "autoscaling/v2beta2":
            cpu = 0
            for metric in autoscaler.status.current_metrics:
                if metric.type == "Resource":
                    if metric.resource.name == "cpu":
                        cpu_util = metric.resource.current.average_utilization
                        break
            hpa_status["current_cpu_utilization_percentage"] = cpu_util
        else:
            raise TestRunError(
                "unsupported HPA version {}".format(autoscaler.api_version))

    def get_deployment_pods(self, deployment_name):
        pod_list = self.core_v1_api.list_namespaced_pod(
            namespace=self.user_args["k8s_namespace"])
        pods = {}
        for item in pod_list.items:
            if item.metadata.name.startswith(self.deployment_name):
                ready_status = False
                for condition in item.status.conditions:
                    if (condition.type == 'Ready' and condition.status == 'True'):
                        ready_status = True
                        break
                pods[item.metadata.name] = {
                    "pod_ip": item.status.pod_ip,
                    "node": item.spec.node_name,
                    "phase": item.status.phase,
                    "ready": ready_status
                }

        return pods

    def monitor_autoscale_status(self, target_cpu, cpu_tolerance):
        while True:
            # get all deployment pods
            pods = self.get_deployment_pods(self.deployment_name)
            if self.user_args["debug"]:
                self._iq.write("pods", str(pods))

            for pod_name in pods.keys():
                if pod_name not in self.pods_dict:
                    self.pods_dict[pod_name] = {"thread": None}
                self.pods_dict[pod_name]["phase"] = pods[pod_name]["phase"]
                self.pods_dict[pod_name]["ready"] = pods[pod_name]["ready"]
                self.pods_dict[pod_name]["pod_ip"] = pods[pod_name]["pod_ip"]
                self.pods_dict[pod_name]["node"] = pods[pod_name]["node"]
                self.pods_dict[pod_name]["cpu_metric"] = None

            # get all pod metrics
            metrics = self.get_deployment_metrics()
            if self.user_args["debug"]:
                self._iq.write("metrics", str(metrics))

            for pod_name in metrics.keys():
                self.pods_dict[pod_name]["cpu_metric"] = metrics[pod_name]["cpu"]

            if self.user_args["debug"]:
                self._iq.write(label="Pod status, count: {}".format(
                    len(self.pods_dict.keys())), value=str(self.pods_dict))

            # create adjuster thread for new created pod
            for pod_name in self.pods_dict.keys():
                if self.pods_dict[pod_name]["ready"] and not self.pods_dict[pod_name]["thread"]:
                    # output other pod metrics 
                    value = [{"pod_name": x, "cpu_metric": self.pods_dict[x]["cpu_metric"]} for x in self.pods_dict.keys() if self.pods_dict[x]["cpu_metric"]]
                    self._iq.write("Pod metrics", str(value))
                    self._iq.write("Scaled up new pod", "pod_name: {}, pod_ip: {}, node: {}".format(
                        pod_name, self.pods_dict[pod_name]["pod_ip"], self.pods_dict[pod_name]["node"]))
                    pod_ip = self.pods_dict[pod_name]["pod_ip"]
                    thread = PodCPUAdjuster(platform_svc_ip=self.user_args["platform_svc_ip"],
                                            api_client=self.api_client,
                                            namespace=self.user_args["k8s_namespace"],
                                            pod_name=pod_name,
                                            pod_ip=self.pods_dict[pod_name]["pod_ip"],
                                            target_cpu=target_cpu,
                                            tolerance=cpu_tolerance,
                                            log=self.log,
                                            iq=self._iq)
                    thread.start()
                    self.pods_dict[pod_name]["thread"] = thread

            pod_stable_flags = [
                x["thread"].stable_flag for x in self.pods_dict.values() if x["thread"]]
            if all(pod_stable_flags) and len(pod_stable_flags) == self.max_replicas:
                value = [{"pod_name": x, "pod_ip": self.pods_dict[x]["pod_ip"], "node": self.pods_dict[x]
                          ["node"], "metric": self.pods_dict[x]["cpu_metric"]} for x in self.pods_dict.keys()]
                self._iq.write("Scale up to max replicas {} done".format(
                    self.max_replicas), value)
                break

            time.sleep(self.user_args["scale_query_interval"])

    def scale_down_deployment(self):
        # stop adjuster thread
        self.stop_http_client()

        # wait until pod count to min replicas
        while True:
            pods = self.get_deployment_pods(self.deployment_name)
            if len(pods) == self.min_replicas:
                break

    def get_pod_cpu_request(self):
        cpu_request = 0
        pod_list = self.core_v1_api.list_namespaced_pod(
            namespace=self.user_args["k8s_namespace"])
        for item in pod_list.items:
            if item.metadata.name.startswith(self.deployment_name):
                cpu_str = item.spec.containers[0].resources.requests["cpu"]
                cpu_request = int(cpu_str.rstrip('m'))

        return cpu_request

    def get_max_min_replicas_in_hpa(self):
        self.log.info("enter get_max_min_replicas_in_hpa.")
        try:
            resp = self.autoscaling_api.read_namespaced_horizontal_pod_autoscaler(
                self.hpa_name, self.user_args["k8s_namespace"], _preload_content=False)
        except Exception as e:
            self._log.error("update hpa error: %s" % str(e))
            raise TestRunError("update target cpu util %d fail!" % cpu_util)
        autoscaler = json.loads(resp.data.decode('utf-8'))
        # return int(autoscaler.spec.max_replicas), int(autoscaler.spec.min_replicas)
        return int(autoscaler["spec"]["maxReplicas"]), int(autoscaler["spec"]["minReplicas"])

    def get_deployment_init_replicas(self):
        deployment = self.apps_v1_api.read_namespaced_deployment(
            name=self.deployment_name, namespace=self.user_args["k8s_namespace"])
        return deployment.spec.replicas

    def do_init_pods_in_deployment(self, target_cpu, cpu_tolerance):        
        # get all deployment pods
        pods = self.get_deployment_pods(self.deployment_name)
        # self._iq.write("pods", str(pods))
        for pod_name in pods.keys():
            if pod_name not in self.pods_dict:
                self.pods_dict[pod_name] = {"thread": None}
            self.pods_dict[pod_name]["phase"] = pods[pod_name]["phase"]
            self.pods_dict[pod_name]["ready"] = pods[pod_name]["ready"]
            self.pods_dict[pod_name]["pod_ip"] = pods[pod_name]["pod_ip"]
            self.pods_dict[pod_name]["node"] = pods[pod_name]["node"]
            self.pods_dict[pod_name]["cpu_metric"] = None

        # get all pod metrics
        metrics = self.get_deployment_metrics()
        # self._iq.write("metrics", str(metrics))
        for pod_name in metrics.keys():
            self.pods_dict[pod_name]["cpu_metric"] = metrics[pod_name]["cpu"]

        for pod_name in self.pods_dict.keys():
            self._iq.write("Initial pod(s) in deployment", "pod_name: {}, pod_ip: {}, node: {}, metric: {}".format(
                pod_name, self.pods_dict[pod_name]["pod_ip"], self.pods_dict[pod_name]["node"], self.pods_dict[pod_name]["cpu_metric"]))
            if self.pods_dict[pod_name]["ready"] and not self.pods_dict[pod_name]["thread"]:
                pod_ip = self.pods_dict[pod_name]["pod_ip"]
                thread = PodCPUAdjuster(platform_svc_ip=self.user_args["platform_svc_ip"],
                                        api_client=self.api_client,
                                        namespace=self.user_args["k8s_namespace"],
                                        pod_name=pod_name,
                                        pod_ip=self.pods_dict[pod_name]["pod_ip"],
                                        target_cpu=target_cpu,
                                        tolerance=cpu_tolerance,
                                        log=self.log,
                                        iq=self._iq)
                thread.start()
                self.pods_dict[pod_name]["thread"] = thread

        return

    def get_http_server_svc_ip(self):
        svc = self._k8s_client.v1_core_api.read_namespaced_service(
            name=self.server_svc_name,
            namespace=self.user_args["k8s_namespace"]
        )

        return svc.spec.cluster_ip

    def start_http_client_rate(self, rate):
        # construct redirect url via platform service as http proxy
        url = "http://" + self.user_args["platform_svc_ip"] + \
            "/redirect/" + self.http_client_pod_ip + ":8080/start"
        payload = {
            "target_url": "http://" + self.http_server_svc_ip + "/cpuload.php",
            "rate": rate,
            "count": self.user_args["calc_count"]
        }

        # need to align with http client api definition
        resp = requests.post(url, json=payload)
        if 200 != resp.status_code:
            self._log.error(
                "start http client rate fail, err: {}".format(resp.text))
            raise TestRunError(
                "start http client rate fail, err: {}".format(resp.text))
        return

    def stop_http_client(self):
        # construct redirect url via platform service as http proxy
        url = "http://" + self.user_args["platform_svc_ip"] + \
            "/redirect/" + self.http_client_pod_ip + ":8080/stop"
        payload = {
            "target_url": "http://" + self.http_server_svc_ip + "/cpu",
        }
        # need to align with http client api definition
        resp = requests.post(url, json=payload)
        if 200 != resp.status_code:
            self._log.error(
                "stop http client rate fail, err: {}".format(resp.text))
            raise TestRunError(
                "stop http client rate fail, err: {}".format(resp.text))
        return

    def trigger_and_monitor_autoscale_status(self):
        self.pods = self.get_deployment_pods(self.deployment_name)
        self._iq.write("Init pod in deployment", str(self.pods))

        self.current_rate = self.user_args.get("http_base_rate", 20)
        self.step_rate = self.user_args.get("step_rate", 10)      

        while True:
            # start http rate
            self.start_http_client_rate(self.current_rate)
            time.sleep(self.user_args.get("stablization_secs", 60))

            pods = self.get_deployment_pods(self.deployment_name)

            if len(pods) != len(self.pods):
                for pod_name in pods.keys():
                    if pod_name not in self.pods.keys():
                        self._iq.write("Scaled new pod", pod_name + ":" + str(pods[pod_name]))
                self.pods = pods
            else:
                # output current metrics
                metrics = self.get_deployment_metrics()
                self._iq.write("Http rate {}".format(self.current_rate), str(metrics))

            if len(pods) >= self.max_replicas:
                break

            self.current_rate += self.step_rate
      
    def get_http_client_pod_ip(self):
        client_deployment_name = self.user_args["clientName"] + "-deployment"
        pod_list = self.core_v1_api.list_namespaced_pod(namespace=self.user_args["k8s_namespace"],
                                                        label_selector="app=http-client")
        pod = None
        for item in pod_list.items:
            if item.metadata.name.startswith(client_deployment_name):
                pod = item
        if not pod:
            raise TestRunError("can't find client pod resource.")

        return pod.status.pod_ip

    def run(self, user_args: dict) -> None:
        """ Execute the user script.

        :param user_args: User-supplied test case arguments. The contents of the dict can be set to the values
            described in the class documentation. All or a subset of the options may be set.
        """
        self.user_args = user_args

        # construct resources name which will be used afterwards
        self.deployment_name = self.user_args["serverName"] + "-deployment"
        self.server_svc_name = self.user_args["serverName"] + "-svc"
        self.hpa_name = self.user_args["serverName"] + "-hpa"

        self.http_client_pod_ip = self.get_http_client_pod_ip()
        self._log.info("http_client_pod_ip: %s" % self.http_client_pod_ip)
        self.http_server_svc_ip = self.get_http_server_svc_ip()
        self._log.info("http_server_svc_ip: %s" % self.http_server_svc_ip)

        # construct corespondent autoscaling api object, input version must be same as helm chart version
        if self.user_args["autoscaling_version"] == "v1":
            self.autoscaling_api = AutoscalingV1Api(self.api_client)
        elif self.user_args["autoscaling_version"] == "v2beta2":
            self.autoscaling_api = AutoscalingV2beta2Api(self.api_client)
        else:
            raise TestInputError("unsupported HPA version {}".format(
                self.user_args["autoscaling_version"]))

        # query pod cpu request
        cpu_request = self.get_pod_cpu_request()
        # query max replicas in hpa
        self.max_replicas, self.min_replicas = self.get_max_min_replicas_in_hpa()
        self.deployment_init_replicas = self.get_deployment_init_replicas()
        self._iq.write("Chart configuration", "pod_cpu_request: {}, deployment_init_replicas: {}, hpa_min_replicas: {}, hpa_max_replicas: {}".format(
            str(cpu_request), self.deployment_init_replicas, self.min_replicas, self.max_replicas))

        self._iq.write(label="Start HPA test", value="")

        for cpu_util in self.user_args["cpu_util_list"]:
            self._iq.write(label="Start CPU util",
                           value="cpu_util: {}".format(cpu_util))
            self.update_target_cpu_util_in_hpa(cpu_util)
            # sleep some time to make hpa effective
            time.sleep(10)
            self.trigger_and_monitor_autoscale_status()
            self._iq.write(label="End CPU util",
                           value="cpu_util: {}".format(cpu_util))

            # stop cpu load to make deployment scale down to 1
            self.scale_down_deployment()
            self._iq.write("Scalce down to min replicas {} complete".format(
                self.min_replicas), "")

        self._iq.write(label="End HPA test", value="")
