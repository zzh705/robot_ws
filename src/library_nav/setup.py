from setuptools import find_packages, setup

package_name = 'library_nav'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        (
            'share/ament_index/resource_index/packages',
            ['resource/' + package_name]
        ),
        (
            'share/' + package_name,
            ['package.xml']
        ),
        (
            'share/' + package_name + '/launch',
            ['launch/nav.launch.py']
        ),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='root',
    maintainer_email='root@todo.todo',
    description='Self-developed A* + DWA + PID navigation stack',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'global_planner_node = library_nav.global_planner_node:main',
            'local_planner_node = library_nav.local_planner_node:main',
            'pid_controller_node = library_nav.pid_controller_node:main',
            'goal_bridge_node = library_nav.goal_bridge_node:main',
        ],
    },
)