#!/usr/bin/python
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

DOCUMENTATION = '''
---
module: ec2_asg_copy
short_description: copies an Auto Scaling group within a region
description:
    - Copies an Auto Scaling Group within a region including Scaling Polices
    and Alarms. This module has a dependency on python-boto >= 2.5
version_added: "2.0"
options:
  region:
    description:
      - the region in which this action will be performed
    required: true
  source_asg_name:
    description:
      - the source Auto Scaling Group name that will be copied
    required: true
  name:
    description:
      - The name of the new Auto Scaling Group
    required: true
    default: null

author: Brock Haywood <brock.haywood@gmail.com>
extends_documentation_fragment: aws
'''

EXAMPLES = '''
# Basic ASG Copy
- local_action:
    module: ec2_asg_copy
    region: us-east-1
    source_asg_name: asg-xxxxxxx
    name: SuperService-new-ASG
  register: asg_id
'''

import time
import logging as log

from ansible.module_utils.basic import *
from ansible.module_utils.ec2 import *
log.getLogger('boto').setLevel(log.CRITICAL)

try:
    import boto.ec2.autoscale
    import boto.ec2.cloudwatch
    from boto.ec2.autoscale import AutoScaleConnection, AutoScalingGroup, Tag
    from boto.ec2.cloudwatch import MetricAlarm
    from boto.exception import BotoServerError
    HAS_BOTO = True
except ImportError:
    HAS_BOTO = False


def copy_auto_scaling_group(as_connection, cloudwatch_connection, module):
    """
    Copies an ASG

    module : AnsibleModule object
    ec2: authenticated ec2 connection object
    """

    source_asg_name = module.params.get('source_asg_name')
    group_name = module.params.get('group_name')
    launch_config_name = module.params.get('launch_config_name')
    load_balancers = module.params.get('launch_config_name')
    wait_for_instances = module.params.get('wait_for_instances')
    wait_timeout = module.params.get('wait_timeout')

    try:

        groups = as_connection.get_all_groups(names=[source_asg_name])

        if len(groups) == 1:
            source_group = groups[0]
            source_policies = as_connection.get_all_policies(
                as_group=source_asg_name)
            launch_config = as_connection.get_all_launch_configurations(
                names=[launch_config_name]
            )[0]

            ag = AutoScalingGroup(
                group_name=group_name,
                load_balancers=[load_balancers]
                    if load_balancers else source_group.load_balancers,
                availability_zones=source_group.availability_zones,
                launch_config=launch_config,
                min_size=source_group.min_size,
                max_size=source_group.max_size,
                desired_capacity=source_group.desired_capacity,
                vpc_zone_identifier=source_group.vpc_zone_identifier,
                connection=source_group.connection,
                tags=source_group.tags,
                health_check_period=source_group.health_check_period,
                health_check_type=source_group.health_check_type,
                default_cooldown=source_group.default_cooldown,
                termination_policies=source_group.termination_policies)

            try:
                as_connection.create_auto_scaling_group(ag)
                if wait_for_instances is True:
                    wait_for_new_inst(
                        module,
                        connection,
                        group_name,
                        wait_timeout,
                        desired_capacity,
                        'viable_instances')
                    wait_for_elb(as_connection, module, group_name)

                as_group = as_connection.get_all_groups(names=[group_name])[0]
                asg_properties = get_properties(as_group)

                for policy in source_policies:
                    policy.as_group = as_group.name
                    as_connection.create_scaling_policy(policy)
                    if policy.scaling_adjustment > 0:
                        alarm_name = '{}-ScaleUp'.format(source_asg_name)
                    else:
                        alarm_name = '{}-ScaleDown'.format(source_asg_name)
                    alarm = cloudwatch_connection.describe_alarms(
                        alarm_names=[alarm_name])[0]
                    alarm.dimensions['AutoScalingGroupName'] = as_group.name
                    cloudwatch_connection.create_alarm(alarm)

                changed = True
                return(changed, asg_properties)
            except BotoServerError, e:
                module.fail_json(msg=str(e))

        else:
            module.fail_json(
                msg='Unable to find source group {}'.format(source_asg_name))


def main():
    argument_spec = ec2_argument_spec()
    argument_spec.update(dict(
        region=dict(required=True),
        source_asg_name=dict(required=True),
        name=dict(required=True)))

    module = AnsibleModule(argument_spec=argument_spec)

    if not HAS_BOTO:
        module.fail_json(msg='boto required for this module')

    region, ec2_url, aws_connect_params = get_aws_connection_info(module)

    try:
        as_connection = connect_to_aws(
            boto.ec2.autoscale, region, **aws_connect_params)
        cloudwatch_connection = connect_to_aws(
            boto.ec2.cloudwatch, region, **aws_connect_params)
        if not as_connection or not cloudwatch_connection:
            module.fail_json(
                msg="failed to connect to AWS for the "
                "given region: %s" % str(region))
    except boto.exception.NoAuthHandlerFound, e:
        module.fail_json(msg=str(e))

    changed, new_asg_properties = copy_auto_scaling_group(
        as_connection, cloudwatch_connection, module)

    module.exit_json(changed=True, **new_asg_properties)


main()
