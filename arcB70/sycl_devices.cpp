#include <sycl/sycl.hpp>
#include <iostream>

int main() {
    try {
        auto devices = sycl::device::get_devices(sycl::info::device_type::gpu);
        for (size_t i = 0; i < devices.size(); ++i) {
            auto &d = devices[i];
            if (!d.has(sycl::aspect::ext_intel_pci_address)) continue;
            std::cout << i << '\t' << d.get_info<sycl::info::device::vendor_id>() << '\t'
                      << d.get_info<sycl::ext::intel::info::device::device_id>() << '\t'
                      << d.get_info<sycl::ext::intel::info::device::pci_address>() << '\t'
                      << d.get_info<sycl::info::device::global_mem_size>() << '\t'
                      << d.get_info<sycl::info::device::name>() << '\n';
        }
    } catch (const sycl::exception &e) {
        std::cerr << "SYCL GPU enumeration failed: " << e.what() << '\n';
        return 1;
    }
}
