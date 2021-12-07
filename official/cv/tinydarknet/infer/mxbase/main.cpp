/*
 * Copyright 2021 Huawei Technologies Co., Ltd
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
#include "TinydarknetClassify.h"
#include <dirent.h>
#include "MxBase/Log/Log.h"

namespace {
    const uint32_t CLASS_NUM = 1000;
    const double THOUSAND = 1000.0;
}    // namespace

APP_ERROR ScanImages(const std::string &path, std::vector<std::string> &imgFiles) {
    DIR *dirPtr = opendir(path.c_str());
    if (dirPtr == nullptr) {
        LogError << "opendir failed. dir:" << path;
        return APP_ERR_INTERNAL_ERROR;
    }
    dirent *direntPtr = nullptr;
    while ((direntPtr = readdir(dirPtr)) != nullptr) {
        std::string fileName = direntPtr->d_name;
        if (fileName == "." || fileName == "..") {
            continue;
        }

        imgFiles.emplace_back(path + "/" + fileName);
    }
    closedir(dirPtr);
    return APP_ERR_OK;
}

int main(int argc, char* argv[]) {
    if (argc <= 1) {
        LogWarn << "Please input image path, such as './tinydarknet image_dir'.";
        return APP_ERR_OK;
    }

    InitParam initParam = {};
    initParam.deviceId = 0;
    initParam.classNum = CLASS_NUM;
    initParam.labelPath = "../data/config/imagenet1000_clsidx_to_labels.names";
    initParam.topk = 5;
    initParam.softmax = false;
    initParam.checkTensor = true;
    initParam.modelPath = "../data/models/tinydarknet.om";

    auto tinydarknet = std::make_shared<TinydarknetClassify>();
    APP_ERROR ret = tinydarknet->Init(initParam);
    if (ret != APP_ERR_OK) {
        LogError << "TinydarknetClassify init failed, ret=" << ret << ".";
        return ret;
    }

    std::string imgPath = argv[1];
    std::vector<std::string> imgFilePaths;
    ret = ScanImages(imgPath, imgFilePaths);
    if (ret != APP_ERR_OK) {
        tinydarknet->DeInit();
        return ret;
    }

    auto startTime = std::chrono::high_resolution_clock::now();

    for (auto &imgFile : imgFilePaths) {
        ret = tinydarknet->Process(imgFile);
        if (ret != APP_ERR_OK) {
            LogError << "TinydarknetClassify process failed, ret=" << ret << ".";
            tinydarknet->DeInit();
            return ret;
        }
    }

    auto endTime = std::chrono::high_resolution_clock::now();
    tinydarknet->DeInit();
    double costMilliSecs = std::chrono::duration<double, std::milli>(endTime - startTime).count();
    double fps = THOUSAND * imgFilePaths.size() / tinydarknet->GetInferCostMilliSec();
    LogInfo << "[Process Delay] cost: " << costMilliSecs << " ms\tfps: " << fps << " imgs/sec";

    return APP_ERR_OK;
}
