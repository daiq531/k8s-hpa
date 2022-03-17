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


class MonitorThread(Thread):
    def __init__(self, script, start_time, cpu_util, http_rate, timeout=180, query_interval=1):
        self.script = script
        self.start_time = start_time
        self.cpu_util = cpu_util
        self.http_rate = http_rate
        self.run_flag = True

    def run():
        while self.run_flag:
            now = time.monotonic()
            if (now - self.start_time) > timeout:
                self.script.event.set()
                self.script._iq.write(label="Monitor duration timeout",
                                      value="start time: {}, end time: {}".format(self.start_time, now))
                break

            # query and output hpa status and
            hpa_status = self.script.get_hpa_status(self.script.hpa_name)
            self.script._iq.write(label="HPA status under CPU util: {}, Http rate: {}".format(self.cpu_util, self.http_rate),
                                  value=str(hpa_status))
            pod_metric_list = self.script.get_deployment_metrics(
                self.script.deployment_name)
            self.script._iq.write(label="POD metrics under CPU util: {}, Http rate: {}".format(self.cpu_util, self.http_rate),
                                  value=str(pod_metric_list))
            # also exit if judge scale complete
            time.sleep(query_interval)

        return


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
        (list) http_rate_list: the list of http rate to be iterated to trigger autoscaling, rate unit: reqs/min
        (int) watch_timeout: timeout seconds value of each watching for utilization and load rate combination
        (int) scaling_query_interval: the interval senconds of querying current scaling status
        (str) autoscaling_version: must be align with HPA version used in Helm chart
    """

    # monitor duration for each new http rate load,
    # monitor_duration = metrics_collection_interval * TIMES_FOR_MONITOR
    TIMES_FOR_MONITOR = 3

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
        self._ssh = ssh
        self._k8s_client = k8s_client
        self._iq = iq_res.label_value_writer

        # construct related api object which will be used
        self.api_client = k8s_client.v1_core_api.api_client
        self.core_v1_api = k8s_client.v1_core_api
        self.apps_v1_api = k8s_client.v1_app_api

    def validate_user_args(self):
        # ensure user args have mandatory fields
        pass

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
            if str(exception) == 'Invalid value for `conditions`, must not be `None`':
                self._log.info('Skipping invalid \'conditions\' value...')
        except Exception as e:
            self._log.error("update hpa error: %s" % str(e))
            raise TestRunError("update target cpu util %d fail!" % cpu_util)

        self._log.info("update target cpu util %d complete!" % cpu_util)

        return

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

    '''
    def get_http_client_pod_ip(self):
        pod = self._k8s_client.v1_core_api.read_namespaced_pod_status(
            name=self.client_pod_name,
            namespace=self.user_args["k8s_namespace"])

        # get pod ip from status
        return pod.status.pod_ip
    '''

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
            "target_url": "http://" + self.http_server_svc_ip + "/cpu",
            "rate": rate
        }

        # need to align with http client api definition
        resp = requests.post(url, json=payload)
        if 200 != resp.status_code:
            self._log.error(
                "start http client rate fail, err: {}".format(resp.text))
            raise TestRunError("start http client rate fail, err: {}".format(resp.text))
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
            raise TestRunError("stop http client rate fail, err: {}".format(resp.text))
        return

    def get_deployment_metrics(self, deployment_name) -> list:
        '''
        Get metrics of pods in deployment.
        See: https://github.com/kubernetes-client/python/issues/1247
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
        pod_metric_list = []
        for item in data["items"]:
            if item["metadata"]["name"].startswith(self.user_args["serverName"] + "-deployment"):
                pod_metric = {
                    "name": item["metadata"]["name"],
                    "cpu": item["containers"][0]["usage"]["cpu"],
                    "memory": item["containers"][0]["usage"]["memory"]
                }
                pod_metric_list.append(pod_metric)
        return pod_metric_list

    def get_hpa_status(self, hpa_name):
        autoscaler = self.autoscaling_api.read_namespaced_horizontal_pod_autoscaler_status(
            hpa_name, self.user_args["k8s_namespace"])
        hpa_status = {
            "hpa_name": hpa_name,
            "hpa_version": autoscaler.api_version,
            "current_replicas": autoscaler.status.current_replicas,
            "desired_replicas": autoscaler.status.desired_replicas
        }
        if autoscaler.api_version == "autoscaling/v1":
            hpa_status["current_cpu_utilization_percentage"] = autoscaler.status.current_cpu_utilization_percentage
        else:
            raise TestRunError(
                "unsupported HPA version {}".format(autoscaler.api_version))

        return hpa_status

    def get_server_pods_status(self, deployment_name):
        pod_list = self.core_v1_api.list_namespaced_pod(namespace=self.user_args["k8s_namespace"])
        pod_status_list = []
        for item in pod_list.items:
            if item.metadata.name.startswith(self.user_args["serverName"] + "-deployment"):
                pod_status = {
                    "pod_name": item.metadata.name,
                    "node": item.spec.node_name,
                    "phase": item.status.phase
                }
                pod_status_list.append(pod_status)

        return pod_status_list

    def monitor_hpa_status(self, cpu_util, http_rate):
        iter_start_time = time.monotonic()
        while True:
            now = time.monotonic()
            if (now - iter_start_time) > self.user_args["watch_timeout"]:
                self._iq.write(label="Monitor duration timeout",
                               value="start time: {}, end time: {}".format(iter_start_time, now))
                break

            # query and output hpa status and pod metrics
            hpa_status = self.get_hpa_status(self.hpa_name)
            self._iq.write(label="HPA status under CPU util: {}, Http rate: {}".format(cpu_util, http_rate),
                           value=str(hpa_status))
            pod_metric_list = self.get_deployment_metrics(self.deployment_name)
            self._iq.write(label="POD metrics under CPU util: {}, Http rate: {}".format(cpu_util, http_rate),
                           value=str(pod_metric_list))
            # query pod and compute node association
            pod_status_list = self.get_server_pods_status(self.deployment_name)
            self._iq.write(label="POD node association", value=str(pod_status_list))

            # also exit if judge scale complete
            '''
            # below judgement can not be used across different cpu util because it is true when run second cpu_util
            if (hpa_status["current_replicas"] == hpa_status["desired_replicas"]) \
                    and (hpa_status["current_replicas"] == len(pod_status_list)):
                self._iq.write(label="Scaling operation complete",
                               value="start time: {}, end time: {}".format(iter_start_time, now))
                break
            '''
            time.sleep(int(self.user_args["scaling_query_interval"]))

    def run(self, user_args: dict) -> None:
        """ Execute the user script.

        :param user_args: User-supplied test case arguments. The contents of the dict can be set to the values
            described in the class documentation. All or a subset of the options may be set.
        """
        self.user_args = user_args

        # construct corespondent autoscaling api object, input version must be same as helm chart version
        if self.user_args["autoscaling_version"] == "v1":
            self.autoscaling_api = AutoscalingV1Api(self.api_client)
        elif self.user_args["autoscaling_version"] == "v2beta2":
            self.autoscaling_api = AutoscalingV2beta2Api(self.api_client)
        else:
            raise TestInputError("unsupported HPA version {}".format(
                self.user_args["autoscaling_version"]))

        # construct resources name which will be used afterwards
        self.deployment_name = self.user_args["serverName"] + "-deployment"
        self.server_svc_name = self.user_args["serverName"] + "-svc"
        self.hpa_name = self.user_args["serverName"] + "-hpa"
        # self.client_pod_name = self.user_args["clientName"] + "-pod"

        # acquire http client and http server svc ip.
        # Don't need wait because wait option has been set in helm install command
        self.http_client_pod_ip = self.get_http_client_pod_ip()
        self._log.info("http_client_pod_ip: %s" % self.http_client_pod_ip)
        self.http_server_svc_ip = self.get_http_server_svc_ip()
        self._log.info("http_server_svc_ip: %s" % self.http_server_svc_ip)

        # create event to sync with monitor thread
        self.event = Event()

        self._iq.write(label="Start HPA test", value="")
        for cpu_util in self.user_args["cpu_util_list"]:
            self._iq.write(label="Start CPU util",
                           value="cpu_util: {}".format(cpu_util))
            self.update_target_cpu_util_in_hpa(cpu_util)
            # sleep some time to make hpa effective
            time.sleep(10)
            for http_rate in self.user_args["http_rate_list"]:
                self._iq.write(label="Start http client rate",
                               value="http_rate: {}".format(http_rate))
                self.start_http_client_rate(http_rate)
                self.rate_time_begin = time.monotonic()
                self.monitor_hpa_status(cpu_util, http_rate)
                self._iq.write(label="End http client rate",
                               value="http_rate: {}".format(http_rate))
            self._iq.write(label="End CPU util",
                           value="cpu_util: {}".format(cpu_util))
            
            # stop http traffic until replicas return to 1
            self._iq.write(label="Stop http client begin under cpu util: {}".format(cpu_util), value="")
            self.stop_http_client()
            while True:
                pod_status_list = self.get_server_pods_status(self.deployment_name)
                self._iq.write(label="POD status", value=str(pod_status_list))
                if len(pod_status_list) == 1:
                    break
                time.sleep(int(self.user_args["scaling_query_interval"]) * 2)
            self._iq.write(label="Stop http client end under cpu util: {}".format(cpu_util), value="")

        self._iq.write(label="End HPA test", value="")
